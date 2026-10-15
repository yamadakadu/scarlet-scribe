"""Protocolo `Connector`, independente de ferramenta.

O `SyncService` só conhece este módulo e os modelos de `domain/`. Cada
ferramenta (por exemplo `connectors/clickup/`) implementa o protocolo e mantém
os próprios tipos dentro do seu subpacote.

Listagem completa ou parcial (ver `ARCHITECTURE.md` › "Sincronização"):
um registro só pode ganhar `deleted_at` se a listagem daquele passo terminou sem
nenhum erro **e** buscou tudo (modo `full`). Por isso a estrutura e as tarefas
vêm acompanhadas de um `ListingReport`, que diz o modo (`report.mode`), se a
listagem foi completa (`report.complete`) e se ela autoriza exclusões
(`report.allows_deletions`), e traz os erros por recurso, os registros
descartados e as buscas que compõem a listagem, prontos para `stats`.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
import enum
from dataclasses import dataclass, field
from datetime import datetime
from types import TracebackType
from typing import Any, Protocol, Self, runtime_checkable

from scarlet_scribe.domain.models import (
    Commit,
    Container,
    MergeRequest,
    Person,
    Repository,
    Task,
    Workspace,
)

# --- Erros -----------------------------------------------------------------


class ConnectorError(Exception):
    """Erro base de qualquer conector. A mensagem nunca contém credenciais."""


class ConnectorAuthError(ConnectorError):
    """Credencial inválida ou revogada (HTTP 401). O sync deve falhar."""


class ConnectorConfigError(ConnectorError):
    """Configuração ausente ou inválida (token, workspace)."""


# --- Relatório de uma listagem ---------------------------------------------


@dataclass(frozen=True)
class FetchIssue:
    """Problema num recurso específico, sem conteúdo do registro.

    - `resource`: o que falhou, por exemplo `space`, `folder`, `list`, `spaces`,
      `tasks` ou `task`.
    - `external_id`: id do recurso na origem, no mesmo formato dos modelos
      canônicos (containers com o prefixo de nível, por exemplo `folder:456`).
      Pode ser nulo quando não há id (por exemplo, uma página de tarefas).
    - `reason`: motivo curto (status HTTP, campo inválido). Nunca traz nomes,
      e-mails, conteúdo de tarefas ou credenciais.
    """

    resource: str
    external_id: str | None
    reason: str
    status_code: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "resource": self.resource,
            "external_id": self.external_id,
            "reason": self.reason,
            "status_code": self.status_code,
        }


class ListingMode(enum.StrEnum):
    """O que a listagem se propôs a buscar."""

    # Tudo o que existe na origem (estrutura; tarefas na reconciliação).
    FULL = "full"
    # Só o que mudou desde um instante (tarefas com `updated_since`). Mesmo
    # completa, uma listagem incremental **nunca** autoriza exclusões: o que não
    # veio pode simplesmente não ter mudado.
    INCREMENTAL = "incremental"


@dataclass
class ListingPart:
    """Uma das buscas que compõem a listagem (por exemplo, tarefas ativas,
    arquivadas e marcos).

    - `finished`: a busca foi até o fim, sem erro;
    - `received`: registros recebidos nela, contando repetidos e descartados.
    """

    finished: bool = False
    received: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {"finished": self.finished, "received": self.received}


@dataclass
class ListingReport:
    """Como terminou uma listagem (estrutura ou tarefas).

    - `mode`: `full` (buscou tudo) ou `incremental` (só o que mudou). Só uma
      listagem `full` e completa pode marcar exclusões; `complete=True` no modo
      incremental quer dizer apenas "nada falhou", e **não** autoriza
      exclusões. Use `allows_deletions`, que já combina os dois.
    - `errors`: falhas que deixaram a listagem **parcial** (403/404 ou resposta
      fora do formato num space, folder ou list; página de tarefas que falhou;
      timeout persistente). Qualquer erro aqui proíbe marcar exclusões.
    - `discarded`: registros que vieram da origem mas foram descartados por dados
      inválidos (por exemplo, uma data que não converte). O registro existe na
      origem: na reconciliação, trate os ids de `discarded_ids` como "vistos",
      para não marcá-los como excluídos. Um descartado **sem id** torna a
      listagem parcial.
    - `parts`: as buscas que compõem a listagem, por nome (nas tarefas do
      ClickUp: `archived`, `archived_milestones`, `milestones` e `tasks`). A listagem só é completa se
      todas terminaram sem erro. Vazio quando a listagem é uma busca só.
    - `finished`: a iteração foi até o fim. Uma iteração interrompida pelo
      consumidor (ou por exceção) não conta como completa.
    """

    mode: ListingMode = ListingMode.FULL
    errors: list[FetchIssue] = field(default_factory=list)
    discarded: list[FetchIssue] = field(default_factory=list)
    parts: dict[str, ListingPart] = field(default_factory=dict)
    finished: bool = False

    @property
    def complete(self) -> bool:
        """True só se a listagem terminou, sem erros, com todas as buscas
        terminadas e sem descartados sem id. Não diz nada sobre o modo: ver
        `allows_deletions`."""
        return (
            self.finished
            and not self.errors
            and all(part.finished for part in self.parts.values())
            and all(issue.external_id is not None for issue in self.discarded)
        )

    @property
    def is_full(self) -> bool:
        return self.mode is ListingMode.FULL

    @property
    def allows_deletions(self) -> bool:
        """`complete` e `full`: a única combinação que autoriza `deleted_at`.

        É condição necessária, não suficiente: a reconciliação de tarefas exige
        também a estrutura completa no mesmo run (regra do sync).
        """
        return self.complete and self.is_full

    @property
    def discarded_ids(self) -> set[str]:
        return {issue.external_id for issue in self.discarded if issue.external_id is not None}

    def to_stats(self) -> dict[str, Any]:
        """Resumo serializável para `sync_runs.stats` (contadores e ids, sem conteúdo)."""
        return {
            "mode": self.mode.value,
            "complete": self.complete,
            "allows_deletions": self.allows_deletions,
            "errors": len(self.errors),
            "discarded": len(self.discarded),
            "parts": {name: part.to_dict() for name, part in self.parts.items()},
            "error_details": [issue.to_dict() for issue in self.errors],
            "discarded_details": [issue.to_dict() for issue in self.discarded],
        }


# --- Resultados ------------------------------------------------------------


@dataclass
class StructureSnapshot:
    """Estrutura de um workspace: o workspace, as pessoas e a árvore de containers.

    `containers` vem em ordem de pai para filho, space a space: o space, depois
    as folders em ordem topológica (a pai sempre antes da filha, inclusive em
    subfolders), depois as lists. Uma folder cujo pai não veio na listagem sai
    depois das demais folders do space, com o `external_parent_id` preservado;
    quem grava não deve supor que esse pai existe. A estrutura é sempre `full`:
    `report.allows_deletions` (igual a `report.complete` aqui) diz se dá para
    marcar exclusões.
    """

    workspace: Workspace
    people: list[Person]
    containers: list[Container]
    report: ListingReport


type TaskBatchSource = Callable[[ListingReport], AsyncIterator[list[Task]]]


class TaskListing:
    """Tarefas em lotes (uma página por lote), iteráveis uma única vez.

        listing = connector.iter_tasks(updated_since=...)
        async for batch in listing:
            ...  # upsert do lote
        if listing.report.allows_deletions:  # completa e `full`
            ...  # só aqui pode marcar exclusões

    O `report` é preenchido durante a iteração; leia-o depois do `async for`.
    Cada id de tarefa sai no máximo uma vez na listagem inteira.
    Erros que deixam a listagem parcial **não** interrompem com exceção: a
    iteração termina, e o erro fica em `report.errors` (inclusive 5xx ou 429
    persistentes e resposta fora do formato numa página). Na iteração das
    tarefas, só `ConnectorAuthError` e `ConnectorConfigError` saem como
    exceção. Para `fetch_structure`, que tem outro contrato, ver o protocolo.
    """

    def __init__(self, source: TaskBatchSource, *, mode: ListingMode = ListingMode.FULL) -> None:
        self.report = ListingReport(mode=mode)
        self._source = source
        self._started = False

    def __aiter__(self) -> AsyncIterator[list[Task]]:
        if self._started:
            raise RuntimeError("uma TaskListing só pode ser iterada uma vez")
        self._started = True
        return self._run()

    async def _run(self) -> AsyncIterator[list[Task]]:
        async for batch in self._source(self.report):
            yield batch
        self.report.finished = True


@dataclass
class RepositorySnapshot:
    """Repositórios de uma fonte de código. Sempre a listagem completa (`full`).

    `report.allows_deletions` (igual a `report.complete` aqui) diz se dá para
    marcar exclusões. As `parts` têm uma entrada por grupo (`group:<id>`) e por
    projeto avulso (`project:<id>`) configurados.
    """

    repositories: list[Repository]
    report: ListingReport


type BatchSource[T] = Callable[[ListingReport], AsyncIterator[list[T]]]


class BatchListing[T]:
    """Registros em lotes (uma página por lote), iteráveis uma única vez.

    O mesmo contrato do `TaskListing`, para qualquer tipo de registro:

        listing = connector.iter_merge_requests(repo_id, updated_since=...)
        async for batch in listing:
            ...  # upsert do lote
        if listing.report.allows_deletions:  # completa e `full`
            ...

    O `report` é preenchido durante a iteração; leia-o depois do `async for`.
    Erros que deixam a listagem parcial **não** interrompem com exceção: a
    iteração termina e o erro fica em `report.errors`. Só `ConnectorAuthError` e
    `ConnectorConfigError` saem como exceção.
    """

    def __init__(self, source: BatchSource[T], *, mode: ListingMode = ListingMode.FULL) -> None:
        self.report = ListingReport(mode=mode)
        self._source = source
        self._started = False

    def __aiter__(self) -> AsyncIterator[list[T]]:
        if self._started:
            raise RuntimeError("uma BatchListing só pode ser iterada uma vez")
        self._started = True
        return self._run()

    async def _run(self) -> AsyncIterator[list[T]]:
        async for batch in self._source(self.report):
            yield batch
        self.report.finished = True


# --- Protocolo -------------------------------------------------------------


@runtime_checkable
class Connector(Protocol):
    """Fonte de dados somente leitura de uma ferramenta.

    Uma instância por execução de sync, usada como async context manager, que
    garante o fechamento das conexões:

        async with create_connector(settings) as connector:
            structure = await connector.fetch_structure()
            listing = connector.iter_tasks(updated_since=watermark)
            async for batch in listing:
                ...

    Todos os registros devolvidos são modelos de `domain/`, com
    `source == connector.source`.
    """

    @property
    def source(self) -> str:
        """Nome da ferramenta de origem, gravado em `source` (por exemplo `clickup`)."""
        ...

    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None: ...

    async def fetch_structure(self) -> StructureSnapshot:
        """Workspace, pessoas e containers. Sempre a listagem completa da estrutura.

        Erros num recurso abaixo do workspace (space, folder, list) **não** saem
        como exceção: vão para `report.errors` e a estrutura fica parcial. Um
        403/404 ou uma resposta 200 fora do formato deixa a busca seguir para os
        outros recursos; outros erros (5xx, 429 ou timeout persistentes) a
        interrompem ali.

        Exceções (o sync trata todas como fatais: run `failed`):
        - `ConnectorAuthError`: credencial inválida ou revogada (401);
        - `ConnectorConfigError`: configuração ausente ou workspace não visível;
        - `ConnectorError` (qualquer outra subclasse): o workspace e as pessoas
          não puderam ser lidos (5xx, timeout ou 429 persistentes, resposta fora
          do formato). Sem o workspace, não há o que gravar.

        O chamador deve capturar `ConnectorError`, a base das três.
        """
        ...

    def iter_tasks(self, *, updated_since: datetime | None = None) -> TaskListing:
        """Tarefas (com subtarefas, fechadas e marcos), em lotes.

        - `updated_since=None`: modo `full` (reconciliação).
        - `updated_since=<datetime com fuso>`: modo `incremental`, só as tarefas
          alteradas depois desse instante. A margem de segurança é do chamador.
          Uma listagem incremental nunca autoriza exclusões.

        Inclui as tarefas arquivadas (com `Task.archived = True`).
        """
        ...


@runtime_checkable
class CodeConnector(Protocol):
    """Fonte de código somente leitura (repositórios, merge requests e commits).

    Protocolo separado do `Connector` (que tem o formato de gerenciamento de
    tarefas do ClickUp). Uma instância por execução de sync, usada como async
    context manager:

        async with create_code_connector(settings) as connector:
            snapshot = await connector.fetch_repositories()
            for repo in snapshot.repositories:
                mrs = connector.iter_merge_requests(repo.external_id, updated_since=...)
                async for batch in mrs:
                    ...
                commits = connector.iter_commits(repo.external_id, since=...)
                async for batch in commits:
                    ...

    Todos os registros devolvidos são modelos de `domain/`, com
    `source == connector.source`. Os ids de repositório são os `external_id` de
    `Repository`.
    """

    @property
    def source(self) -> str:
        """Nome da ferramenta de origem, gravado em `source` (por exemplo `gitlab`)."""
        ...

    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None: ...

    async def fetch_repositories(self) -> RepositorySnapshot:
        """Repositórios configurados (grupos com subgrupos e arquivados, sem os compartilhados
        de outros grupos, mais os projetos avulsos), sem repetir. Sempre a listagem completa.

        Erros num recurso (grupo ou projeto) **não** saem como exceção: vão para
        `report.errors` e a listagem fica parcial. 403/404, resposta fora do
        formato e paginação que não termina deixam a busca seguir para os outros
        recursos; outros erros (5xx, 429 ou timeout persistentes) a interrompem ali.

        Exceções (o sync trata como fatais): `ConnectorAuthError` (401) e
        `ConnectorConfigError`. O chamador deve capturar `ConnectorError`, a base.
        """
        ...

    def iter_merge_requests(
        self, repository_id: str, *, updated_since: datetime | None = None
    ) -> BatchListing[MergeRequest]:
        """Merge requests de um repositório (todos os estados), em lotes.

        - `updated_since=None`: modo `full`.
        - `updated_since=<datetime com fuso>`: modo `incremental`, só os MRs
          alterados depois desse instante. A margem de segurança é do chamador.
          Uma listagem incremental nunca autoriza exclusões.

        Cada `external_id` sai no máximo uma vez. `MergeRequest.author` traz a
        `Person` do autor, para o sync gravar em `people`. Um erro de recurso
        (403, inclusive MRs desativados no projeto, ou 404) vai para
        `report.errors`. `report.parts` tem a busca `merge_requests`.
        """
        ...

    def iter_commits(
        self, repository_id: str, *, since: datetime | None = None
    ) -> BatchListing[Commit]:
        """Commits de um repositório em todos os branches, em lotes.

        - `since=None`: modo `full`; com `datetime` com fuso, `incremental`.
        - Cada sha sai no máximo uma vez na iteração.
        - Erros de recurso vão para `report.errors`; um repositório vazio pode
          responder 404. `report.parts` tem a busca `commits`.
        """
        ...


__all__ = [
    "BatchListing",
    "CodeConnector",
    "Connector",
    "ConnectorAuthError",
    "ConnectorConfigError",
    "ConnectorError",
    "FetchIssue",
    "ListingMode",
    "ListingPart",
    "ListingReport",
    "RepositorySnapshot",
    "StructureSnapshot",
    "TaskListing",
]
