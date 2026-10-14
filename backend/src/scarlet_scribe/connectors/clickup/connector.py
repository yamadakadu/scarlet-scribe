"""`ClickUpConnector`: implementa o protocolo `Connector` com `client` + `mapper`.

- Uma instância de `ClickUpClient` por execução, fechada no `__aexit__`.
- Somente GET (o cliente não tem outra coisa).
- Respeita `CLICKUP_SPACE_IDS`; vazio = todos os spaces visíveis ao token.
- 401 propaga (`ClickUpAuthError`, que é um `ConnectorAuthError`): o sync falha.
- 403/404 num space, folder ou list vira erro daquele recurso em
  `report.errors`, e a busca segue. A listagem passa a ser parcial.
- Outros erros (5xx ou timeout persistentes, resposta fora do formato,
  paginação quebrada) também vão para `report.errors`, mas interrompem a busca
  daquele passo, que fica parcial.
- Tarefa com dado inválido (por exemplo, uma data que não converte) é
  descartada sozinha: vai para `report.discarded` com id e motivo, sem conteúdo.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from datetime import datetime
from functools import partial
from types import TracebackType
from typing import TYPE_CHECKING, Any, Self

from pydantic import ValidationError

from scarlet_scribe.connectors.base import (
    FetchIssue,
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

# Busca extra de marcos (`custom_items[]=1`), unida à busca padrão sem duplicar.
# O spike não conseguiu confirmar que a busca sem `custom_items[]` traz os marcos
# (o workspace de teste não tem nenhum). Custa cerca de uma página a mais por
# sync. Quando o comportamento for confirmado, basta trocar para False (ou passar
# `fetch_milestones_separately=False`).
FETCH_MILESTONES_SEPARATELY = True


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
            spaces = await self._call(report, "spaces", None, self._client.get_spaces(self._team_id))
            if spaces is None:
                spaces = []
            if self._space_ids:
                visible = {s.id for s in spaces}
                for missing in (s for s in self._space_ids if s not in visible):
                    report.errors.append(
                        FetchIssue("space", space_ref(missing), "space configurado não está visível ao token")
                    )
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
            build = partial(map_list, lst, workspace_id=workspace_id, space_id=space.id)
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
        report: ListingReport, resource: str, external_id: str | None, call: Awaitable[T]
    ) -> T | None:
        """Executa uma chamada da estrutura e classifica o erro.

        401 e configuração propagam. 403/404 viram erro do recurso e devolvem
        `None` (a busca segue). Qualquer outro erro do ClickUp é registrado e
        interrompe a busca (`_StopWalk`).
        """
        try:
            return await call
        except (ClickUpAuthError, ClickUpConfigError):
            raise
        except ClickUpResourceError as exc:
            report.errors.append(_issue(resource, external_id, exc))
            logger.warning("ClickUp: %s %s ignorado (%s)", resource, external_id or "", exc)
            return None
        except ClickUpError as exc:
            report.errors.append(_issue(resource, external_id, exc))
            logger.warning("ClickUp: busca da estrutura interrompida em %s %s (%s)",
                           resource, external_id or "", exc)
            raise _StopWalk from None

    # --- Tarefas -----------------------------------------------------------

    def iter_tasks(self, *, updated_since: datetime | None = None) -> TaskListing:
        """Tarefas em lotes (uma página por lote): incremental com `updated_since`, completa sem.

        Busca padrão (subtarefas e fechadas incluídas, sem `archived`) e, se
        `fetch_milestones_separately`, uma busca extra com `custom_items[]=1`.
        As duas são unidas sem repetir ids.
        """
        date_updated_gt = datetime_to_ms(updated_since) if updated_since is not None else None
        return TaskListing(lambda report: self._task_batches(report, date_updated_gt))

    async def _task_batches(
        self, report: ListingReport, date_updated_gt: int | None
    ) -> AsyncIterator[list[Task]]:
        searches: list[tuple[str, tuple[int, ...] | None]] = [("tasks", None)]
        if self._fetch_milestones_separately:
            searches.append(("milestones", (MILESTONE_CUSTOM_ITEM_ID,)))

        seen: set[str] = set()
        for label, custom_items in searches:
            pages = self._client.iter_task_pages(
                self._team_id,
                date_updated_gt=date_updated_gt,
                space_ids=self._space_ids or None,
                custom_items=custom_items,
            )
            try:
                async for page in pages:
                    batch = self._map_page(page.tasks, page.invalid, seen, report)
                    if batch:
                        yield batch
            except (ClickUpAuthError, ClickUpConfigError):
                raise
            except ClickUpError as exc:
                report.errors.append(_issue("tasks", None, exc, prefix=f"busca {label}"))
                logger.warning("ClickUp: busca de tarefas (%s) interrompida (%s)", label, exc)
                return

    @staticmethod
    def _map_page(
        tasks: Sequence[ClickUpTask], invalid: Sequence[InvalidTask], seen: set[str], report: ListingReport
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
                batch.append(map_task(task))
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
