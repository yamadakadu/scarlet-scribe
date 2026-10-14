"""`ClickUpConnector`: implementa o protocolo `Connector` com `client` + `mapper`.

- Uma instância de `ClickUpClient` por execução, fechada no `__aexit__`.
- Somente GET (o cliente não tem outra coisa).
- Respeita `CLICKUP_SPACE_IDS`; vazio = todos os spaces visíveis ao token.
- 401 propaga (`ClickUpAuthError`, que é um `ConnectorAuthError`): o sync falha.
- Estrutura: 403/404 ou resposta 200 fora do formato numa chamada de um
  recurso (spaces, um space, uma folder) vira erro daquele recurso em
  `report.errors`, e a busca segue para os outros. A listagem fica parcial.
  Outros erros (5xx, 429 ou timeout persistentes) também vão para
  `report.errors`, mas interrompem a busca da estrutura.
- Tarefas: até quatro buscas no mesmo endpoint, com os mesmos filtros, unidas
  sem repetir ids, nesta ordem: `archived` (`archived=true`, só arquivadas),
  `archived_milestones` (`archived=true&custom_items[]=1`), `milestones`
  (`custom_items[]=1`) e `tasks` (a padrão). As duas de marcos dependem de
  `fetch_milestones_separately` e são ligadas ou desligadas juntas. Vale a
  primeira aparição de cada id; como as arquivadas vêm antes, uma tarefa que
  aparece também em outra busca sai com `archived=True`, e `is_milestone` vem
  sempre do `custom_item_id` do payload.
  Um erro numa busca (qualquer um, menos 401 e configuração) vai para
  `report.errors`, encerra aquela busca e a listagem segue para a próxima;
  a listagem fica parcial.
- Tarefa com dado inválido (por exemplo, uma data que não converte) é
  descartada sozinha: vai para `report.discarded` com id e motivo, sem conteúdo.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from functools import partial
from types import TracebackType
from typing import TYPE_CHECKING, Any, Self

from pydantic import ValidationError

from scarlet_scribe.connectors.base import (
    FetchIssue,
    ListingMode,
    ListingPart,
    ListingReport,
    StructureSnapshot,
    TaskListing,
)
from scarlet_scribe.connectors.clickup.client import (
    ClickUpAuthError,
    ClickUpClient,
    ClickUpConfigError,
    ClickUpError,
    ClickUpHTTPError,
    ClickUpResourceError,
    ClickUpResponseError,
    InvalidTask,
    validation_reason,
)
from scarlet_scribe.connectors.clickup.mapper import (
    MILESTONE_CUSTOM_ITEM_ID,
    SOURCE,
    MappingError,
    datetime_to_ms,
    folder_ref,
    list_ref,
    map_folder,
    map_list,
    map_members,
    map_space,
    map_task,
    map_workspace,
    space_ref,
)
from scarlet_scribe.domain.models import Container, Task

if TYPE_CHECKING:
    from scarlet_scribe.config import Settings
    from scarlet_scribe.connectors.clickup.schemas import (
        ClickUpFolder,
        ClickUpSpace,
        ClickUpTask,
    )

logger = logging.getLogger(__name__)

# Buscas extras de marcos (`custom_items[]=1`), ativas e arquivadas, unidas às
# demais sem duplicar. O spike não conseguiu confirmar que a busca sem
# `custom_items[]` traz os marcos (o workspace de teste não tem nenhum); sem a
# busca de marcos arquivados, um marco arquivado sumiria da listagem e ganharia
# `deleted_at`. Custam cerca de duas páginas a mais por sync. Quando o
# comportamento for confirmado, basta trocar para False (ou passar
# `fetch_milestones_separately=False`), o que desliga as duas juntas.
FETCH_MILESTONES_SEPARATELY = True


@dataclass(frozen=True)
class _TaskSearch:
    """Uma das buscas em `GET /v2/team/{id}/task` que compõem a listagem."""

    name: str
    archived: bool = False
    custom_items: tuple[int, ...] | None = None


# Ordem importa: vale a primeira aparição de cada id, e as arquivadas vêm antes
# para que `archived=True` prevaleça sobre uma aparição nas outras buscas.
_ARCHIVED_SEARCH = _TaskSearch("archived", archived=True)
_ARCHIVED_MILESTONES_SEARCH = _TaskSearch(
    "archived_milestones", archived=True, custom_items=(MILESTONE_CUSTOM_ITEM_ID,)
)
_MILESTONES_SEARCH = _TaskSearch("milestones", custom_items=(MILESTONE_CUSTOM_ITEM_ID,))
_DEFAULT_SEARCH = _TaskSearch("tasks")


class _StopWalk(Exception):
    """Interrompe a busca da estrutura depois de um erro que não é de um recurso só."""


class ClickUpConnector:
    """Conector somente leitura do ClickUp (token do bot).

        async with ClickUpConnector.from_settings(settings) as connector:
            structure = await connector.fetch_structure()
            listing = connector.iter_tasks(updated_since=watermark)
            async for batch in listing:
                ...
            listing.report.complete
    """

    source = SOURCE

    def __init__(
        self,
        client: ClickUpClient,
        *,
        team_id: str,
        space_ids: Sequence[str] = (),
        fetch_milestones_separately: bool = FETCH_MILESTONES_SEPARATELY,
    ) -> None:
        if not team_id:
            raise ClickUpConfigError("CLICKUP_TEAM_ID não está definido")
        self._client = client
        self._team_id = str(team_id)
        # Ordem preservada, sem repetição.
        self._space_ids = list(dict.fromkeys(str(s) for s in space_ids))
        self._fetch_milestones_separately = fetch_milestones_separately

    @classmethod
    def from_settings(
        cls,
        settings: Settings,
        *,
        space_ids: Sequence[str] | None = None,
        fetch_milestones_separately: bool = FETCH_MILESTONES_SEPARATELY,
        **client_kwargs: Any,
    ) -> Self:
        """Conector do bot. `space_ids=None` usa `CLICKUP_SPACE_IDS`; `[]` = todos os spaces."""
        if not settings.clickup_team_id:
            raise ClickUpConfigError("CLICKUP_TEAM_ID não está definido")
        client = ClickUpClient.from_settings(settings, **client_kwargs)
        return cls(
            client,
            team_id=settings.clickup_team_id,
            space_ids=settings.clickup_space_ids if space_ids is None else space_ids,
            fetch_milestones_separately=fetch_milestones_separately,
        )

    def __repr__(self) -> str:
        return f"ClickUpConnector(spaces={len(self._space_ids) or 'todos'}, client={self._client!r})"

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self._client.aclose()

    # --- Estrutura ---------------------------------------------------------

    async def fetch_structure(self) -> StructureSnapshot:
        """Workspace, members e a árvore space > folder > list (sempre completa).

        Erros no `GET /v2/team` propagam: sem o workspace não há o que gravar.
        Um `CLICKUP_TEAM_ID` que não está entre os workspaces do token é
        `ClickUpConfigError`.
        """
        teams = await self._client.get_teams()
        team = next((t for t in teams if t.id == self._team_id), None)
        if team is None:
            raise ClickUpConfigError("CLICKUP_TEAM_ID não está entre os workspaces visíveis ao token")

        workspace = map_workspace(team)
        people = map_members(team)
        containers: list[Container] = []
        report = ListingReport()

        try:
            prefix = (
                f"listagem dos spaces falhou; nenhum dos {len(self._space_ids)} space(s) de "
                "CLICKUP_SPACE_IDS foi percorrido"
                if self._space_ids
                else "listagem dos spaces falhou; nenhum space foi percorrido"
            )
            spaces = await self._call(
                report, "spaces", None, self._client.get_spaces(self._team_id), prefix=prefix
            )
            if spaces is None:
                # Um erro só (o da listagem). Sem ela, não dá para dizer quais spaces
                # configurados estão visíveis, então não há erro por space.
                spaces = []
            elif self._space_ids:
                visible = {s.id for s in spaces}
                for missing in (s for s in self._space_ids if s not in visible):
                    report.errors.append(
                        FetchIssue(
                            "space",
                            space_ref(missing),
                            "space de CLICKUP_SPACE_IDS ausente da listagem de spaces do token "
                            "(não existe, está arquivado ou o bot não tem acesso)",
                        )
                    )
            if self._space_ids:
                wanted = set(self._space_ids)
                spaces = [s for s in spaces if s.id in wanted]
            for space in spaces:
                await self._walk_space(space, workspace.external_id, containers, report)
        except _StopWalk:
            pass
        else:
            report.finished = True

        if report.errors:
            logger.warning("ClickUp: estrutura parcial (%d erro(s) por recurso)", len(report.errors))
        return StructureSnapshot(workspace=workspace, people=people, containers=containers, report=report)

    async def _walk_space(
        self,
        space: ClickUpSpace,
        workspace_id: str,
        containers: list[Container],
        report: ListingReport,
    ) -> None:
        sref = space_ref(space.id)
        self._add(containers, report, sref, partial(map_space, space, workspace_id=workspace_id))

        raw_folders = await self._call(report, "space", sref, self._client.get_folders(space.id))
        # Subfolders podem vir antes da pai: ordena para manter pai → filho.
        folders = parents_first(raw_folders or [])
        for folder in folders:
            build = partial(map_folder, folder, workspace_id=workspace_id, space_id=space.id)
            self._add(containers, report, folder_ref(folder.id), build)
        for folder in folders:
            fref = folder_ref(folder.id)
            lists = await self._call(report, "folder", fref, self._client.get_folder_lists(folder.id))
            for lst in lists or []:
                build = partial(
                    map_list, lst, workspace_id=workspace_id, space_id=space.id, folder_id=folder.id
                )
                self._add(containers, report, list_ref(lst.id), build)

        folderless = await self._call(report, "space", sref, self._client.get_folderless_lists(space.id))
        for lst in folderless or []:
            build = partial(map_list, lst, workspace_id=workspace_id, space_id=space.id, folderless=True)
            self._add(containers, report, list_ref(lst.id), build)

    @staticmethod
    def _add(
        containers: list[Container], report: ListingReport, ref: str, build: Callable[[], Container]
    ) -> None:
        try:
            containers.append(build())
        except (MappingError, ValidationError) as exc:
            reason = validation_reason(exc) if isinstance(exc, ValidationError) else str(exc)
            report.discarded.append(FetchIssue(ref.split(":", 1)[0], ref, reason))
            logger.warning("ClickUp: container %s descartado (%s)", ref, reason)

    @staticmethod
    async def _call[T](
        report: ListingReport,
        resource: str,
        external_id: str | None,
        call: Awaitable[T],
        *,
        prefix: str = "",
    ) -> T | None:
        """Executa uma chamada da estrutura e classifica o erro.

        401 e configuração propagam. 403/404 e resposta 200 fora do formato
        (`ClickUpResponseError`) são problemas daquele recurso: viram erro dele
        e devolvem `None` (a busca segue para os outros). Qualquer outro erro do
        ClickUp (5xx, 429 ou timeout persistentes) é registrado e interrompe a
        busca (`_StopWalk`), porque tende a se repetir nas chamadas seguintes.
        """
        try:
            return await call
        except (ClickUpAuthError, ClickUpConfigError):
            raise
        except (ClickUpResourceError, ClickUpResponseError) as exc:
            report.errors.append(_issue(resource, external_id, exc, prefix=prefix))
            logger.warning("ClickUp: %s %s ignorado (%s)", resource, external_id or "", exc)
            return None
        except ClickUpError as exc:
            report.errors.append(_issue(resource, external_id, exc, prefix=prefix))
            logger.warning("ClickUp: busca da estrutura interrompida em %s %s (%s)",
                           resource, external_id or "", exc)
            raise _StopWalk from None

    # --- Tarefas -----------------------------------------------------------

    def iter_tasks(self, *, updated_since: datetime | None = None) -> TaskListing:
        """Tarefas em lotes (uma página por lote): `incremental` com `updated_since`, `full` sem.

        Até quatro buscas com os mesmos filtros (subtarefas e fechadas
        incluídas, `space_ids[]` e, no incremental, `date_updated_gt`), unidas
        sem repetir ids, nesta ordem: `archived` (`archived=true`),
        `archived_milestones` (`archived=true&custom_items[]=1`), `milestones`
        (`custom_items[]=1`) e `tasks` (a padrão). As duas de marcos só rodam
        com `fetch_milestones_separately`. Cada busca aparece em
        `report.parts`; a listagem só é completa se todas terminaram sem erro.
        """
        date_updated_gt = datetime_to_ms(updated_since) if updated_since is not None else None
        mode = ListingMode.FULL if updated_since is None else ListingMode.INCREMENTAL
        return TaskListing(lambda report: self._task_batches(report, date_updated_gt), mode=mode)

    def _task_searches(self) -> list[_TaskSearch]:
        searches = [_ARCHIVED_SEARCH]
        if self._fetch_milestones_separately:
            searches += [_ARCHIVED_MILESTONES_SEARCH, _MILESTONES_SEARCH]
        searches.append(_DEFAULT_SEARCH)
        return searches

    async def _task_batches(
        self, report: ListingReport, date_updated_gt: int | None
    ) -> AsyncIterator[list[Task]]:
        searches = self._task_searches()
        # Todas registradas desde o início: uma busca que não chegou a rodar
        # (iteração interrompida) conta como não terminada.
        for search in searches:
            report.parts[search.name] = ListingPart()

        seen: set[str] = set()
        for search in searches:
            part = report.parts[search.name]
            pages = self._client.iter_task_pages(
                self._team_id,
                date_updated_gt=date_updated_gt,
                space_ids=self._space_ids or None,
                custom_items=search.custom_items,
                archived=search.archived,
            )
            try:
                async for page in pages:
                    part.received += page.size
                    batch = self._map_page(
                        page.tasks, page.invalid, seen, report, archived=search.archived
                    )
                    if batch:
                        yield batch
            except (ClickUpAuthError, ClickUpConfigError):
                raise
            except ClickUpError as exc:
                report.errors.append(_issue("tasks", None, exc, prefix=f"busca {search.name}"))
                logger.warning("ClickUp: busca de tarefas (%s) interrompida (%s)", search.name, exc)
                continue
            part.finished = True

    @staticmethod
    def _map_page(
        tasks: Sequence[ClickUpTask],
        invalid: Sequence[InvalidTask],
        seen: set[str],
        report: ListingReport,
        *,
        archived: bool = False,
    ) -> list[Task]:
        for item in invalid:
            if item.task_id is not None:
                if item.task_id in seen:
                    continue
                seen.add(item.task_id)
            _discard_task(report, item.task_id, item.reason)

        batch: list[Task] = []
        for task in tasks:
            if task.id in seen:
                continue
            seen.add(task.id)
            try:
                batch.append(map_task(task, archived=archived))
            except MappingError as exc:
                _discard_task(report, task.id, str(exc))
            except ValidationError as exc:
                _discard_task(report, task.id, validation_reason(exc))
        return batch


def parents_first(folders: Sequence[ClickUpFolder]) -> list[ClickUpFolder]:
    """Folders de um space em ordem topológica: a pai sempre antes da filha.

    A API devolve subfolders na mesma lista, em qualquer ordem. Primeiro saem as
    folders sem `parent_folder` e os descendentes delas; depois, as folders cujo
    pai não veio na resposta (com os descendentes), mantendo o `parent_folder`
    no mapeamento; por fim, o que sobrar (ciclos). Dentro de cada grupo, vale a
    ordem da API.
    """
    by_id = {f.id: f for f in folders}
    children: dict[str, list[ClickUpFolder]] = {}
    for f in folders:
        parent = f.parent_folder_id
        if parent and parent != f.id:
            children.setdefault(parent, []).append(f)

    ordered: list[ClickUpFolder] = []
    seen: set[str] = set()

    def emit(root: ClickUpFolder) -> None:
        stack = [root]
        while stack:
            f = stack.pop()
            if f.id in seen:
                continue
            seen.add(f.id)
            ordered.append(f)
            stack.extend(reversed(children.get(f.id, [])))

    for f in folders:
        if not f.parent_folder_id:
            emit(f)
    for f in folders:
        if f.parent_folder_id not in by_id:
            emit(f)
    for f in folders:
        emit(f)
    return ordered


def _discard_task(report: ListingReport, task_id: str | None, reason: str) -> None:
    report.discarded.append(FetchIssue("task", task_id, reason))
    logger.warning("ClickUp: tarefa %s descartada (%s)", task_id or "(sem id)", reason)


def _issue(resource: str, external_id: str | None, exc: ClickUpError, *, prefix: str = "") -> FetchIssue:
    status = exc.status_code if isinstance(exc, ClickUpHTTPError) else None
    reason = f"{prefix}: {exc}" if prefix else str(exc)
    return FetchIssue(resource, external_id, reason, status)


__all__ = ["FETCH_MILESTONES_SEPARATELY", "ClickUpConnector"]
