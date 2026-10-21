"""`GitLabConnector`: implementa o protocolo `CodeConnector` com `client` + `mapper`.

- Uma instância de `GitLabClient` por execução, fechada no `__aexit__`.
- Somente GET (o cliente não tem outra coisa).
- Repositórios: os grupos de `GITLAB_GROUP_IDS` (com subgrupos e arquivados, sem
  projetos compartilhados de outros grupos) e os projetos avulsos de
  `GITLAB_PROJECT_IDS`, sem repetir. Um projeto avulso já
  visto na listagem de um grupo (pelo id ou pelo caminho) não é buscado de novo.
- 401 propaga (`GitLabAuthError`, que é um `ConnectorAuthError`): o sync falha.
- Um erro num recurso (403/404, resposta 200 fora do formato, paginação que não
  termina) vai para `report.errors`, a busca segue para o próximo recurso e a
  listagem fica parcial. Outros erros (5xx, 429 ou timeout persistentes) também
  vão para `report.errors`, mas interrompem a busca.
- MRs e commits: uma busca por repositório, com `report.parts` de uma entrada
  (`merge_requests` ou `commits`). Cada id (ou sha) sai uma vez por iteração.
- Issues: como os MRs (busca `issues`). `fetch_issue_closed_by` é uma chamada por issue e
  levanta erro de recurso (403/404) em vez de registrar em relatório.
- Tags: `iter_tags` é sempre `full` (uma busca `tags`); completa e sem erros
  autoriza exclusões. Cada nome sai uma vez.
- Ícone: `fetch_avatar` valida `Repository.avatar_url` (mesmo host e porta do
  `GITLAB_URL`) e baixa por `GET /projects/:id/avatar`, com tipo e tamanho limitados. Qualquer recusa ou falha
  levanta `AvatarUnavailable(reason)`; 401 segue `GitLabAuthError`.
- Registro com dado inválido (por exemplo, uma data que não converte) é
  descartado sozinho: vai para `report.discarded` com id e motivo, sem conteúdo.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Callable, Sequence
from datetime import datetime
from types import TracebackType
from typing import TYPE_CHECKING, Any, Self

from pydantic import ValidationError

from scarlet_scribe.connectors.base import (
    AvatarUnavailable,
    BatchListing,
    FetchIssue,
    ListingMode,
    ListingPart,
    ListingReport,
    RepositorySnapshot,
)
from scarlet_scribe.connectors.gitlab.client import (
    GitLabAuthError,
    GitLabAvatarRejected,
    GitLabClient,
    GitLabConfigError,
    GitLabError,
    GitLabHTTPError,
    GitLabPage,
    GitLabPaginationError,
    GitLabResourceError,
    GitLabResponseError,
    validation_reason,
)
from scarlet_scribe.connectors.gitlab.mapper import (
    SOURCE,
    MappingError,
    commit_ref,
    map_commit,
    map_issue,
    map_merge_request,
    map_repository,
    map_tag,
    tag_ref,
)
from scarlet_scribe.domain.models import Commit, Issue, MergeRequest, Repository, RepositoryAvatar, RepositoryTag

if TYPE_CHECKING:
    from scarlet_scribe.config import Settings

logger = logging.getLogger(__name__)


class _StopWalk(Exception):
    """Interrompe a busca depois de um erro que não é de um recurso só."""


class GitLabConnector:
    """Conector somente leitura do GitLab (token do bot).

        async with GitLabConnector.from_settings(settings) as connector:
            snapshot = await connector.fetch_repositories()
            listing = connector.iter_merge_requests("123", updated_since=watermark)
            async for batch in listing:
                ...
            listing.report.complete
    """

    source = SOURCE

    def __init__(
        self,
        client: GitLabClient,
        *,
        group_ids: Sequence[str] = (),
        project_ids: Sequence[str] = (),
    ) -> None:
        # Ordem preservada, sem repetição.
        self._group_ids = list(dict.fromkeys(str(g) for g in group_ids))
        self._project_ids = list(dict.fromkeys(str(p) for p in project_ids))
        if not self._group_ids and not self._project_ids:
            raise GitLabConfigError("GITLAB_GROUP_IDS e GITLAB_PROJECT_IDS estão vazios")
        self._client = client

    @classmethod
    def from_settings(cls, settings: Settings, **client_kwargs: Any) -> Self:
        """Conector do bot, com os grupos e projetos de `GITLAB_GROUP_IDS` e `GITLAB_PROJECT_IDS`."""
        client = GitLabClient.from_settings(settings, **client_kwargs)
        return cls(
            client,
            group_ids=settings.gitlab_group_ids,
            project_ids=settings.gitlab_project_ids,
        )

    def __repr__(self) -> str:
        return (
            f"GitLabConnector(groups={len(self._group_ids)}, "
            f"projects={len(self._project_ids)}, client={self._client!r})"
        )

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self._client.aclose()

    # --- Repositórios ------------------------------------------------------

    async def fetch_repositories(self) -> RepositorySnapshot:
        """Repositórios dos grupos e dos projetos avulsos, sem repetir (sempre `full`)."""
        report = ListingReport()
        repositories: list[Repository] = []
        seen_ids: set[str] = set()
        seen_paths: set[str] = set()
        # Todas registradas desde o início: uma busca que não chegou a rodar
        # (busca interrompida) conta como não terminada.
        for group_id in self._group_ids:
            report.parts[f"group:{group_id}"] = ListingPart()
        for project_id in self._project_ids:
            report.parts[f"project:{project_id}"] = ListingPart()

        def add(project: Any) -> None:
            try:
                repo = map_repository(project)
            except (MappingError, ValidationError) as exc:
                reason = validation_reason(exc) if isinstance(exc, ValidationError) else str(exc)
                _discard(report, "repository", str(project.id), reason)
                return
            seen_ids.add(repo.external_id)
            seen_paths.add(repo.path_with_namespace)
            repositories.append(repo)

        try:
            for group_id in self._group_ids:
                part = report.parts[f"group:{group_id}"]
                try:
                    async for page in self._client.iter_group_project_pages(group_id):
                        part.received += page.size
                        for item in page.invalid:
                            _discard(report, "repository", item.item_id, item.reason)
                        for project in page.items:
                            if str(project.id) not in seen_ids:
                                add(project)
                except GitLabError as exc:
                    self._record(report, "group", group_id, exc)
                    continue
                part.finished = True

            for project_id in self._project_ids:
                part = report.parts[f"project:{project_id}"]
                if project_id in seen_ids or project_id in seen_paths:
                    part.finished = True
                    continue
                try:
                    project = await self._client.get_project(project_id)
                except GitLabError as exc:
                    self._record(report, "project", project_id, exc)
                    continue
                part.received += 1
                part.finished = True
                if str(project.id) not in seen_ids:
                    add(project)
        except _StopWalk:
            pass
        else:
            report.finished = True

        if report.errors:
            logger.warning("GitLab: repositórios parciais (%d erro(s) por recurso)", len(report.errors))
        return RepositorySnapshot(repositories=repositories, report=report)

    @staticmethod
    def _record(report: ListingReport, resource: str, external_id: str | None, exc: GitLabError) -> None:
        """Registra o erro de um recurso. 401 e configuração propagam.

        Erros de recurso (403/404, resposta fora do formato, paginação) deixam a
        busca seguir; qualquer outro (5xx, 429 ou timeout persistentes) a
        interrompe (`_StopWalk`), porque tende a se repetir nas chamadas seguintes.
        """
        if isinstance(exc, (GitLabAuthError, GitLabConfigError)):
            raise exc
        report.errors.append(_issue(resource, external_id, exc))
        if isinstance(exc, (GitLabResourceError, GitLabResponseError, GitLabPaginationError)):
            logger.warning("GitLab: %s %s ignorado (%s)", resource, external_id or "", exc)
            return
        logger.warning("GitLab: busca interrompida em %s %s (%s)", resource, external_id or "", exc)
        raise _StopWalk from None

    # --- Merge requests ----------------------------------------------------

    def iter_merge_requests(
        self, repository_id: str, *, updated_since: datetime | None = None
    ) -> BatchListing[MergeRequest]:
        """MRs de um repositório, `state=all&scope=all`: `incremental` com `updated_since`, `full` sem."""
        repository_id = str(repository_id)
        mode = ListingMode.FULL if updated_since is None else ListingMode.INCREMENTAL

        def pages() -> AsyncIterator[GitLabPage[Any]]:
            return self._client.iter_merge_request_pages(repository_id, updated_after=updated_since)

        def convert(item: Any) -> MergeRequest:
            return map_merge_request(item, project_id=repository_id)

        return BatchListing(
            lambda report: self._batches(
                report, "merge_requests", "merge_request", repository_id, pages(), convert,
                key=lambda item: str(item.id),
            ),
            mode=mode,
        )

    # --- Issues ------------------------------------------------------------

    def iter_issues(
        self, repository_id: str, *, updated_since: datetime | None = None
    ) -> BatchListing[Issue]:
        """Issues de um repositório, `state=all&scope=all`: `incremental` com `updated_since`, `full` sem."""
        repository_id = str(repository_id)
        mode = ListingMode.FULL if updated_since is None else ListingMode.INCREMENTAL

        def pages() -> AsyncIterator[GitLabPage[Any]]:
            return self._client.iter_issue_pages(repository_id, updated_after=updated_since)

        def convert(item: Any) -> Issue:
            return map_issue(item, project_id=repository_id)

        return BatchListing(
            lambda report: self._batches(
                report, "issues", "issue", repository_id, pages(), convert,
                key=lambda item: str(item.id),
            ),
            mode=mode,
        )

    async def fetch_issue_closed_by(self, repository_id: str, iid: int) -> list[MergeRequest]:
        """MRs de `/issues/:iid/closed_by`, sem filtrar por estado (o critério "merged" é de quem consome).

        403/404 levantam `GitLabResourceError` (um `ConnectorResourceError`); 401 levanta
        `GitLabAuthError`. Um item fora do formato levanta `GitLabResponseError`: descartá-lo
        em silêncio poderia esconder um MR mesclado.
        """
        repository_id = str(repository_id)
        path = f"/projects/{repository_id}/issues/{int(iid)}/closed_by"
        result: list[MergeRequest] = []
        seen: set[int] = set()
        async for page in self._client.iter_issue_closed_by_pages(repository_id, iid):
            if page.invalid:
                raise GitLabResponseError(
                    f"GET {path}: {len(page.invalid)} MR(s) fora do formato esperado "
                    f"({page.invalid[0].reason})",
                    path=path,
                )
            for item in page.items:
                if item.id in seen:
                    continue
                seen.add(item.id)
                try:
                    result.append(map_merge_request(item, project_id=repository_id))
                except MappingError as exc:
                    raise GitLabResponseError(f"GET {path}: MR fora do formato esperado ({exc})", path=path) from None
        return result

    # --- Commits -----------------------------------------------------------

    def iter_commits(
        self, repository_id: str, *, since: datetime | None = None
    ) -> BatchListing[Commit]:
        """Commits de um repositório em todos os branches (`all=true`), sem repetir sha."""
        repository_id = str(repository_id)
        mode = ListingMode.FULL if since is None else ListingMode.INCREMENTAL

        def pages() -> AsyncIterator[GitLabPage[Any]]:
            return self._client.iter_commit_pages(repository_id, since=since)

        def convert(item: Any) -> Commit:
            return map_commit(item, project_id=repository_id)

        return BatchListing(
            lambda report: self._batches(
                report, "commits", "commit", repository_id, pages(), convert,
                key=lambda item: commit_ref(repository_id, item.id.strip()),
            ),
            mode=mode,
        )

    # --- Tags --------------------------------------------------------------

    def iter_tags(self, repository_id: str) -> BatchListing[RepositoryTag]:
        """Tags de um repositório. Sempre `full`; cada nome sai uma vez."""
        repository_id = str(repository_id)

        def convert(item: Any) -> RepositoryTag:
            return map_tag(item, project_id=repository_id)

        return BatchListing(
            lambda report: self._batches(
                report, "tags", "tag", repository_id,
                self._client.iter_tag_pages(repository_id), convert,
                key=lambda item: tag_ref(repository_id, item.name),
            ),
            mode=ListingMode.FULL,
        )

    # --- Ícone -------------------------------------------------------------

    async def fetch_avatar(self, repository: Repository) -> RepositoryAvatar:
        """Baixa o ícone do repositório. Recusas e falhas viram `AvatarUnavailable`."""
        url = repository.avatar_url
        if not url:
            raise AvatarUnavailable("repositório sem avatar_url")
        try:
            content_type, data = await self._client.get_avatar(url, repository.external_id)
        except (GitLabAuthError, GitLabConfigError):
            raise
        except GitLabAvatarRejected as exc:
            raise AvatarUnavailable(exc.reason) from None
        except GitLabError as exc:
            raise AvatarUnavailable(f"download falhou: {exc}") from None
        return RepositoryAvatar(content_type=content_type, data=data, source_url=url)

    # --- Núcleo das listagens por repositório ------------------------------

    async def _batches[T](
        self,
        report: ListingReport,
        part_name: str,
        resource: str,
        repository_id: str,
        pages: AsyncIterator[GitLabPage[Any]],
        convert: Callable[[Any], T],
        *,
        key: Callable[[Any], str],
    ) -> AsyncIterator[list[T]]:
        """Itera as páginas, mapeia cada item e descarta repetidos e inválidos.

        `key` dá o `external_id` canônico de um item (o `id` do MR; no commit,
        `<projeto>:<sha>`). Um item inválido é identificado pelo mesmo formato,
        a partir do id bruto da API.
        """
        part = report.parts[part_name] = ListingPart()
        seen: set[str] = set()
        try:
            async for page in pages:
                part.received += page.size
                for bad in page.invalid:
                    bad_id = self._canonical_invalid_id(resource, repository_id, bad.item_id)
                    if bad_id is not None:
                        if bad_id in seen:
                            continue
                        seen.add(bad_id)
                    _discard(report, resource, bad_id, bad.reason)

                batch: list[T] = []
                for item in page.items:
                    item_id = key(item)
                    if item_id in seen:
                        continue
                    seen.add(item_id)
                    try:
                        batch.append(convert(item))
                    except MappingError as exc:
                        _discard(report, resource, item_id, str(exc))
                    except ValidationError as exc:
                        _discard(report, resource, item_id, validation_reason(exc))
                if batch:
                    yield batch
        except (GitLabAuthError, GitLabConfigError):
            raise
        except GitLabError as exc:
            report.errors.append(_issue(resource, repository_id, exc, prefix=f"repositório {repository_id}"))
            logger.warning("GitLab: busca de %s do repositório %s interrompida (%s)",
                           part_name, repository_id, exc)
            return
        part.finished = True

    @staticmethod
    def _canonical_invalid_id(resource: str, repository_id: str, raw_id: str | None) -> str | None:
        if raw_id is not None and resource == "commit":
            return commit_ref(repository_id, raw_id)
        if raw_id is not None and resource == "tag":
            return tag_ref(repository_id, raw_id)
        return raw_id


def _discard(report: ListingReport, resource: str, external_id: str | None, reason: str) -> None:
    report.discarded.append(FetchIssue(resource, external_id, reason))
    logger.warning("GitLab: %s %s descartado (%s)", resource, external_id or "(sem id)", reason)


def _issue(resource: str, external_id: str | None, exc: GitLabError, *, prefix: str = "") -> FetchIssue:
    status = exc.status_code if isinstance(exc, GitLabHTTPError) else None
    reason = f"{prefix}: {exc}" if prefix else str(exc)
    return FetchIssue(resource, external_id, reason, status)


__all__ = ["GitLabConnector"]
