"""Protocolo `Connector`, independente de ferramenta.

O `SyncService` só conhece este módulo e os modelos de `domain/`. Cada
ferramenta (por exemplo `connectors/clickup/`) implementa o protocolo e mantém
os próprios tipos dentro do seu subpacote.

Listagem completa ou parcial (ver `ARCHITECTURE.md` › "Sincronização"):
um registro só pode ganhar `deleted_at` se a listagem daquele passo terminou sem
nenhum erro. Por isso a estrutura e as tarefas vêm acompanhadas de um
`ListingReport`, que diz se a listagem foi completa (`report.complete`) e traz
os erros por recurso e os registros descartados, prontos para `stats`.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import datetime
from types import TracebackType
from typing import Any, Protocol, Self, runtime_checkable

from scarlet_scribe.domain.models import Container, Person, Task, Workspace

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


@dataclass
class ListingReport:
    """Como terminou uma listagem (estrutura ou tarefas).

    - `errors`: falhas que deixaram a listagem **parcial** (403/404 num space,
      folder ou list; página de tarefas que falhou; timeout persistente).
      Qualquer erro aqui proíbe marcar exclusões.
    - `discarded`: registros que vieram da origem mas foram descartados por dados
      inválidos (por exemplo, uma data que não converte). O registro existe na
      origem: na reconciliação, trate os ids de `discarded_ids` como "vistos",
      para não marcá-los como excluídos. Um descartado **sem id** torna a
      listagem parcial.
    - `finished`: a iteração foi até o fim. Uma iteração interrompida pelo
      consumidor (ou por exceção) não conta como completa.
    """

    errors: list[FetchIssue] = field(default_factory=list)
    discarded: list[FetchIssue] = field(default_factory=list)
    finished: bool = False

    @property
    def complete(self) -> bool:
        """True só se a listagem terminou, sem erros e sem descartados sem id."""
        return (
            self.finished
            and not self.errors
            and all(issue.external_id is not None for issue in self.discarded)
        )

    @property
    def discarded_ids(self) -> set[str]:
        return {issue.external_id for issue in self.discarded if issue.external_id is not None}

    def to_stats(self) -> dict[str, Any]:
        """Resumo serializável para `sync_runs.stats` (contadores e ids, sem conteúdo)."""
        return {
            "complete": self.complete,
            "errors": len(self.errors),
            "discarded": len(self.discarded),
            "error_details": [issue.to_dict() for issue in self.errors],
            "discarded_details": [issue.to_dict() for issue in self.discarded],
        }


# --- Resultados ------------------------------------------------------------


@dataclass
class StructureSnapshot:
    """Estrutura de um workspace: o workspace, as pessoas e a árvore de containers.

    `containers` vem em ordem de pai para filho (space, depois os folders, depois
    as lists de cada space). `report.complete` diz se dá para marcar exclusões.
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
        if listing.report.complete:
            ...  # só aqui pode marcar exclusões

    O `report` é preenchido durante a iteração; leia-o depois do `async for`.
    Erros que deixam a listagem parcial **não** interrompem com exceção: a
    iteração termina, e o erro fica em `report.errors`. Só `ConnectorAuthError`
    (e erros de configuração) saem como exceção.
    """

    def __init__(self, source: TaskBatchSource) -> None:
        self.report = ListingReport()
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

        403/404 num recurso vira erro em `report.errors` e a busca segue.
        Levanta `ConnectorAuthError` em 401.
        """
        ...

    def iter_tasks(self, *, updated_since: datetime | None = None) -> TaskListing:
        """Tarefas (com subtarefas, fechadas e marcos), em lotes.

        - `updated_since=None`: modo completo (reconciliação).
        - `updated_since=<datetime com fuso>`: modo incremental, só as tarefas
          alteradas depois desse instante. A margem de segurança é do chamador.
        """
        ...


__all__ = [
    "Connector",
    "ConnectorAuthError",
    "ConnectorConfigError",
    "ConnectorError",
    "FetchIssue",
    "ListingReport",
    "StructureSnapshot",
    "TaskListing",
]
