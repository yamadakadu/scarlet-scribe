"""`SyncService`: executa um run de sync (passos 1 a 3 do `ARCHITECTURE.md`).

1. **Estrutura:** workspace, pessoas e containers. Containers que não vieram
   ganham `deleted_at`, só se a listagem da estrutura veio completa.
2. **Tarefas, modo incremental:** `updated_since = watermark − 5 min`.
3. **Tarefas, reconciliação completa:** no primeiro sync (sem watermark) e a
   cada `SYNC_FULL_RECONCILE_HOURS`. Substitui o passo 2 naquele run. Só marca
   exclusões se a listagem de tarefas **e** a estrutura do mesmo run vieram
   completas.

Cada passo grava numa transação própria (uma falha num passo não desfaz os
anteriores) e, na mesma transação, atualiza `sync_runs.stats`, para a UI ver o
progresso. Quem marca o run como `running` é o worker; este serviço só executa
e grava o status final.

O conector vem de `create_connector(settings)` ou de uma fábrica passada por
parâmetro (útil para exercitar o serviço com um conector falso). Mensagens de
erro e logs nunca levam credenciais nem conteúdo de tarefas: de um
`ConnectorError` usamos a mensagem (o contrato garante que ela não traz
credenciais); de qualquer outra exceção, só o tipo.
"""

from __future__ import annotations

import asyncio
import logging
import traceback
import uuid
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from functools import partial
from typing import Any

from sqlalchemy import Text, Uuid, bindparam, func, literal_column, select, text, update
from sqlalchemy.dialects.postgresql import ARRAY, insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from scarlet_scribe.config import Settings
from scarlet_scribe.connectors.base import (
    Connector,
    ConnectorAuthError,
    ConnectorConfigError,
    ConnectorError,
    ListingReport,
    StructureSnapshot,
)
from scarlet_scribe.connectors.factory import create_connector
from scarlet_scribe.db.models import (
    ContainerRow,
    PersonRow,
    SyncRunRow,
    SyncStateRow,
    TaskRow,
    WorkspaceRow,
    task_assignees,
)
from scarlet_scribe.db.session import get_sessionmaker
from scarlet_scribe.domain.models import Person, Task
from scarlet_scribe.domain.sync import SyncStatus

logger = logging.getLogger(__name__)

ConnectorFactory = Callable[[], Connector]

# Recurso das tarefas em `sync_state` (PK: source, resource).
TASKS_RESOURCE = "tasks"
# Margem do modo incremental: cobre diferença de relógio e alterações concorrentes.
INCREMENTAL_OVERLAP = timedelta(minutes=5)
# Linhas por INSERT (o asyncpg aceita até 32767 parâmetros; tasks tem ~17 colunas).
INSERT_CHUNK = 500
ERROR_MAX_LEN = 300
# Erro gravado num run que não terminou (cancelado no encerramento do worker ou
# deixado em `running` por um crash).
INTERRUPTED_ERROR = "interrompido"

_TEXT_ARRAY = ARRAY(Text)
_UUID_ARRAY = ARRAY(Uuid())


# --- Estado de um run ---------------------------------------------------------


@dataclass
class _Counter:
    created: int = 0
    updated: int = 0
    deleted: int = 0

    def add_upserted(self, rows: Sequence[Any]) -> None:
        created = sum(1 for row in rows if row.inserted)
        self.created += created
        self.updated += len(rows) - created

    def to_dict(self) -> dict[str, int]:
        return {"created": self.created, "updated": self.updated, "deleted": self.deleted}


@dataclass
class _RunState:
    """O que um run acumula: contadores, relatórios e o desfecho."""

    counters: dict[str, _Counter] = field(
        default_factory=lambda: {
            name: _Counter() for name in ("workspaces", "people", "containers", "tasks")
        }
    )
    extra: dict[str, Any] = field(default_factory=dict)
    errors: list[dict[str, str]] = field(default_factory=list)
    wrote: bool = False  # algum passo gravou (commit) dados
    partial: bool = False  # algum passo ficou parcial ou falhou sem ser fatal
    fatal: str | None = None  # erro fatal: o run termina `failed`

    def stats(self) -> dict[str, Any]:
        data: dict[str, Any] = dict(self.extra)
        data.update({name: counter.to_dict() for name, counter in self.counters.items()})
        if self.errors:
            data["errors"] = list(self.errors)
        return data

    def fail(self, step: str, exc: BaseException) -> None:
        self.fatal = _short(f"{step}: {_describe(exc)}")
        _log_exception(f"passo {step}: erro fatal", exc)

    def step_error(self, step: str, exc: BaseException) -> None:
        self.partial = True
        self.errors.append({"step": step, "error": _short(_describe(exc))})
        _log_exception(f"passo {step}: erro, o passo foi desfeito", exc)

    def final_status(self) -> SyncStatus:
        if self.fatal is not None or not self.wrote:
            return SyncStatus.FAILED
        return SyncStatus.PARTIAL if self.partial else SyncStatus.SUCCEEDED


# --- Serviço ------------------------------------------------------------------


class SyncService:
    """Executa um run de sync que o worker já marcou como `running`.

    - `connector_factory`: devolve um `Connector` novo (ainda não aberto). O
      padrão é `create_connector(settings)`.
    - `sessionmaker`: o padrão é o do processo (`db/session.py`).
    """

    def __init__(
        self,
        settings: Settings,
        *,
        sessionmaker: async_sessionmaker[AsyncSession] | None = None,
        connector_factory: ConnectorFactory | None = None,
    ) -> None:
        self._settings = settings
        self._sessionmaker = sessionmaker or get_sessionmaker()
        self._connector_factory = connector_factory or partial(create_connector, settings)

    async def execute(self, run_id: uuid.UUID) -> SyncStatus:
        """Roda os passos 1 a 3 e grava o status final do run. Devolve o status."""
        state = _RunState()
        try:
            await self._run_with_connector(run_id, state)
        except asyncio.CancelledError:
            # Encerramento do worker no meio do run: registra e repassa o cancelamento.
            logger.warning("run %s cancelado no meio da execução", run_id)
            await self._finish(run_id, SyncStatus.FAILED, state.stats(), INTERRUPTED_ERROR)
            raise
        except Exception as exc:  # erro inesperado fora dos passos (por exemplo, no banco)
            state.fail("sync", exc)

        status = state.final_status()
        error = None
        if status is SyncStatus.FAILED:
            error = state.fatal or "nenhum dado foi gravado"
        await self._finish(run_id, status, state.stats(), error)
        tasks = state.counters["tasks"]
        logger.info(
            "run %s terminou: %s (tarefas: %d criadas, %d atualizadas, %d removidas)",
            run_id, status.value, tasks.created, tasks.updated, tasks.deleted,
        )
        return status

    # --- Orquestração ---------------------------------------------------------

    async def _run_with_connector(self, run_id: uuid.UUID, state: _RunState) -> None:
        try:
            connector = self._connector_factory()
        except ConnectorError as exc:
            state.fail("conector", exc)
            return
        try:
            # O `async with` garante o fechamento do conector (cliente HTTP),
            # inclusive em erro ou cancelamento.
            async with connector:
                await self._run_steps(run_id, connector, state)
        except ConnectorError as exc:  # ao abrir ou fechar o conector
            if state.fatal is None:
                state.fail("conector", exc)

    async def _run_steps(self, run_id: uuid.UUID, connector: Connector, state: _RunState) -> None:
        source = connector.source
        state.extra["source"] = source

        # Passo 1: estrutura. Sem ela não há o que gravar: qualquer erro é fatal.
        try:
            snapshot = await connector.fetch_structure()
        except ConnectorError as exc:
            state.fail("estrutura", exc)
            return
        try:
            structure_allows_deletions = await self._step_structure(run_id, source, snapshot, state)
        except Exception as exc:
            state.fail("estrutura", exc)
            return
        state.wrote = True

        # Passo 2 (incremental) ou 3 (reconciliação completa), nunca os dois.
        try:
            await self._step_tasks(run_id, connector, source, structure_allows_deletions, state)
        except (ConnectorAuthError, ConnectorConfigError) as exc:
            state.fail("tarefas", exc)
        except Exception as exc:
            # A transação do passo foi desfeita; a estrutura continua gravada.
            state.step_error("tarefas", exc)

    # --- Passo 1: estrutura -----------------------------------------------------

    async def _step_structure(
        self, run_id: uuid.UUID, source: str, snapshot: StructureSnapshot, state: _RunState
    ) -> bool:
        report = snapshot.report
        complete = report.complete
        # A estrutura é sempre `full`: aqui `allows_deletions` equivale a `complete`.
        allows_deletions = report.allows_deletions
        workspace = snapshot.workspace

        async with self._sessionmaker() as session, session.begin():
            ws_rows = await _upsert(
                session,
                WorkspaceRow,
                [_record(workspace, name=workspace.name)],
                update_columns=("name", "raw"),
            )
            state.counters["workspaces"].add_upserted(ws_rows)
            workspace_id = ws_rows[0].id

            people = _dedupe(snapshot.people)
            person_rows = await _upsert(
                session,
                PersonRow,
                [_record(p, username=p.username, email=p.email) for p in people],
                update_columns=("username", "email", "raw"),
            )
            state.counters["people"].add_upserted(person_rows)

            containers = []
            foreign = 0
            for container in _dedupe(snapshot.containers):
                if container.external_workspace_id != workspace.external_id:
                    foreign += 1  # não deveria acontecer: um snapshot é de um workspace só
                    continue
                containers.append(container)
            if foreign:
                complete = allows_deletions = False
                logger.warning("estrutura: %d container(s) de outro workspace ignorado(s)", foreign)

            container_rows = await _upsert(
                session,
                ContainerRow,
                [
                    _record(
                        c,
                        workspace_id=workspace_id,
                        external_parent_id=c.external_parent_id,
                        kind=c.kind,
                        name=c.name,
                    )
                    for c in containers
                ],
                update_columns=("workspace_id", "external_parent_id", "kind", "name", "raw"),
            )
            state.counters["containers"].add_upserted(container_rows)
            await _resolve_container_parents(session, source)

            if allows_deletions:
                state.counters["containers"].deleted = await _mark_deleted(
                    session, "containers", source, {c.external_id for c in containers}
                )

            structure_stats = report.to_stats()
            if not allows_deletions:
                structure_stats["deletions_skipped"] = True
                structure_stats["deletions_skipped_reason"] = "estrutura parcial"
            if foreign:
                structure_stats["foreign_containers"] = foreign
            state.extra["structure"] = structure_stats
            await _save_progress(session, run_id, state)

        if not complete:
            state.partial = True
            logger.warning("estrutura parcial: nenhuma exclusão de containers neste run")
        logger.info(
            "estrutura gravada: %d pessoa(s), %d container(s), %d container(s) removido(s)",
            len(person_rows), len(container_rows), state.counters["containers"].deleted,
        )
        return allows_deletions

    # --- Passos 2 e 3: tarefas ------------------------------------------------

    async def _step_tasks(
        self,
        run_id: uuid.UUID,
        connector: Connector,
        source: str,
        structure_allows_deletions: bool,
        state: _RunState,
    ) -> None:
        sync_state = await self._load_state(source)
        watermark = sync_state.watermark if sync_state else None
        reconcile = self._reconcile_due(sync_state)
        updated_since = None if reconcile else watermark - INCREMENTAL_OVERLAP  # type: ignore[operator]
        state.extra["mode"] = "full" if reconcile else "incremental"
        logger.info(
            "tarefas: modo %s%s",
            state.extra["mode"],
            f" (desde {updated_since.isoformat()})" if updated_since else "",
        )

        listing_started_at = datetime.now(UTC)
        listing = connector.iter_tasks(updated_since=updated_since)
        counter = state.counters["tasks"]
        seen: set[str] = set()
        max_updated: datetime | None = None

        async with self._sessionmaker() as session, session.begin():
            async for batch in listing:
                tasks = _dedupe(batch)
                if not tasks:
                    continue
                for task in tasks:
                    seen.add(task.external_id)
                    if task.source_updated_at and (max_updated is None or task.source_updated_at > max_updated):
                        max_updated = task.source_updated_at
                rows = await _upsert(
                    session,
                    TaskRow,
                    [_task_values(task) for task in tasks],
                    update_columns=_TASK_UPDATE_COLUMNS,
                )
                counter.add_upserted(rows)
                state.counters["people"].created += await _replace_assignees(
                    session, source, tasks, {row.external_id: row.id for row in rows}
                )

            report = listing.report
            # Um único UPDATE resolve container_id e parent_id de todas as tarefas.
            await _resolve_task_links(session, source)

            listing_stats: dict[str, Any] = report.to_stats()
            reconciled = False
            if reconcile or report.is_full:
                skip_reason = _task_deletions_blocker(
                    report, requested_full=reconcile, structure_allows_deletions=structure_allows_deletions
                )
                if skip_reason is None:
                    # Vistas: as tarefas dos lotes (já unidas, sem repetição) mais
                    # as descartadas por dados inválidos.
                    counter.deleted = await _mark_deleted(
                        session, "tasks", source, seen | report.discarded_ids
                    )
                    reconciled = True
                else:
                    listing_stats["deletions_skipped"] = True
                    listing_stats["deletions_skipped_reason"] = skip_reason

            # O watermark só avança com a listagem completa; nunca anda para trás.
            new_watermark = watermark
            if report.complete and max_updated is not None:
                new_watermark = max(watermark, max_updated) if watermark else max_updated
            last_full_sync_at = listing_started_at if reconciled else None
            if report.complete and (new_watermark != watermark or last_full_sync_at is not None):
                await _save_state(session, source, new_watermark, last_full_sync_at)
            listing_stats["watermark_advanced"] = report.complete and new_watermark != watermark
            listing_stats["reconciled"] = reconciled

            state.extra["task_listing"] = listing_stats
            await _save_progress(session, run_id, state)

        if not report.complete:
            state.partial = True
            logger.warning("tarefas: listagem parcial (%d erro(s)); watermark mantido", len(report.errors))
        logger.info(
            "tarefas gravadas: %d criada(s), %d atualizada(s), %d removida(s)",
            counter.created, counter.updated, counter.deleted,
        )

    def _reconcile_due(self, sync_state: SyncStateRow | None) -> bool:
        """Reconciliação completa: no primeiro sync e a cada `SYNC_FULL_RECONCILE_HOURS`."""
        if sync_state is None or sync_state.watermark is None or sync_state.last_full_sync_at is None:
            return True
        interval = timedelta(hours=self._settings.sync_full_reconcile_hours)
        return datetime.now(UTC) - sync_state.last_full_sync_at >= interval

    async def _load_state(self, source: str) -> SyncStateRow | None:
        async with self._sessionmaker() as session:
            return await session.get(SyncStateRow, (source, TASKS_RESOURCE))

    # --- Fim do run -------------------------------------------------------------

    async def _finish(
        self, run_id: uuid.UUID, status: SyncStatus, stats: dict[str, Any], error: str | None
    ) -> None:
        async with self._sessionmaker() as session, session.begin():
            await session.execute(
                update(SyncRunRow)
                .where(SyncRunRow.id == run_id)
                .values(status=status, finished_at=func.now(), stats=stats, error=error)
            )


def _task_deletions_blocker(
    report: ListingReport, *, requested_full: bool, structure_allows_deletions: bool
) -> str | None:
    """Motivo para **não** marcar exclusões de tarefas, ou None se pode marcar.

    Regra: `allows_deletions` da listagem de tarefas (completa e `full`) e da
    estrutura do mesmo run. Por segurança, o modo do report também precisa ser o
    que o serviço pediu: um report `full` numa busca pedida como incremental
    seria um erro do conector, e marcar exclusões ali apagaria tarefas que só
    não mudaram.
    """
    if report.is_full != requested_full:
        logger.warning(
            "tarefas: modo do report (%s) diferente do pedido; exclusões não marcadas",
            report.mode.value,
        )
        return "modo da listagem diferente do pedido"
    if not report.allows_deletions:
        return "listagem de tarefas parcial"
    if not structure_allows_deletions:
        return "estrutura parcial"
    return None


# --- SQL ----------------------------------------------------------------------

_TASK_UPDATE_COLUMNS = (
    "name",
    "status",
    "status_type",
    "priority",
    "start_date",
    "due_date",
    "done_at",
    "time_estimate_ms",
    "url",
    "is_milestone",
    "archived",
    "source_updated_at",
    "external_container_id",
    "external_parent_id",
    "raw",
)


def _record(record: Any, **columns: Any) -> dict[str, Any]:
    return {"source": record.source, "external_id": record.external_id, "raw": record.raw, **columns}


def _task_values(task: Task) -> dict[str, Any]:
    return _record(task, **{column: getattr(task, column) for column in _TASK_UPDATE_COLUMNS if column != "raw"})


def _dedupe[R](records: Iterable[R]) -> list[R]:
    """Um registro por `external_id` (o último vence): um INSERT ... ON CONFLICT
    não pode atualizar a mesma linha duas vezes."""
    by_id: dict[str, R] = {}
    for record in records:
        by_id[record.external_id] = record  # type: ignore[attr-defined]
    return list(by_id.values())


def _chunks[T](items: Sequence[T], size: int = INSERT_CHUNK) -> Iterable[Sequence[T]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


async def _upsert(
    session: AsyncSession, model: type, rows: list[dict[str, Any]], *, update_columns: Sequence[str]
) -> list[Any]:
    """`INSERT ... ON CONFLICT (source, external_id) DO UPDATE` em lotes.

    O `set_` envia sempre `synced_at = now()` e `deleted_at = NULL`: um registro
    que reaparece perde o soft delete. Devolve `(id, external_id, inserted)` por
    linha; `inserted` vem de `xmax = 0` (linha nova, não atualizada).
    """
    result: list[Any] = []
    for chunk in _chunks(rows):
        stmt = insert(model).values(list(chunk))
        set_: dict[str, Any] = {column: stmt.excluded[column] for column in update_columns}
        set_["synced_at"] = func.now()
        set_["deleted_at"] = None
        stmt = stmt.on_conflict_do_update(index_elements=["source", "external_id"], set_=set_).returning(
            model.id, model.external_id, literal_column("(xmax = 0)").label("inserted")
        )
        result.extend((await session.execute(stmt)).all())
    return result


async def _replace_assignees(
    session: AsyncSession, source: str, tasks: Sequence[Task], task_ids: dict[str, uuid.UUID]
) -> int:
    """Substitui o conjunto de `task_assignees` das tarefas recebidas.

    Pessoas que só aparecem como assignee entram com `ON CONFLICT DO NOTHING`
    (os dados de `members` têm prioridade). Devolve quantas pessoas foram criadas.
    """
    people: dict[str, Person] = {}
    for task in tasks:
        for person in task.assignees:
            people[person.external_id] = person

    created = 0
    person_ids: dict[str, uuid.UUID] = {}
    if people:
        rows = [_record(p, username=p.username, email=p.email) for p in people.values()]
        for chunk in _chunks(rows):
            stmt = (
                insert(PersonRow)
                .values(list(chunk))
                .on_conflict_do_nothing(index_elements=["source", "external_id"])
                .returning(PersonRow.id)
            )
            created += len((await session.execute(stmt)).all())
        lookup = select(PersonRow.external_id, PersonRow.id).where(
            PersonRow.source == source,
            PersonRow.external_id == func.any(bindparam("ids", list(people), type_=_TEXT_ARRAY)),
        )
        person_ids = {row.external_id: row.id for row in (await session.execute(lookup)).all()}

    ids = list(task_ids.values())
    await session.execute(
        task_assignees.delete().where(
            task_assignees.c.task_id == func.any(bindparam("task_ids", ids, type_=_UUID_ARRAY))
        )
    )
    pairs = {
        (task_ids[task.external_id], person_ids[person.external_id])
        for task in tasks
        if task.external_id in task_ids
        for person in task.assignees
        if person.external_id in person_ids
    }
    for chunk in _chunks(sorted(pairs)):
        await session.execute(
            insert(task_assignees)
            .values([{"task_id": t, "person_id": p} for t, p in chunk])
            .on_conflict_do_nothing()
        )
    return created


# Resolve parent_id a partir de external_parent_id num UPDATE ... FROM único. O
# LEFT JOIN zera o parent_id quando o pai mudou para um que não está no banco
# ou quando external_parent_id ficou nulo.
_RESOLVE_CONTAINER_PARENTS = text(
    """
    UPDATE containers AS c
    SET parent_id = r.new_parent_id
    FROM (
        SELECT child.id, parent.id AS new_parent_id
        FROM containers AS child
        LEFT JOIN containers AS parent
          ON parent.source = child.source AND parent.external_id = child.external_parent_id
        WHERE child.source = :source
    ) AS r
    WHERE c.id = r.id AND c.parent_id IS DISTINCT FROM r.new_parent_id
    """
)

# Mesmo esquema para container_id (por external_container_id) e parent_id (por
# external_parent_id) das tarefas, num único UPDATE.
_RESOLVE_TASK_LINKS = text(
    """
    UPDATE tasks AS t
    SET container_id = r.new_container_id, parent_id = r.new_parent_id
    FROM (
        SELECT task.id, container.id AS new_container_id, parent.id AS new_parent_id
        FROM tasks AS task
        LEFT JOIN containers AS container
          ON container.source = task.source AND container.external_id = task.external_container_id
        LEFT JOIN tasks AS parent
          ON parent.source = task.source AND parent.external_id = task.external_parent_id
        WHERE task.source = :source
    ) AS r
    WHERE t.id = r.id
      AND (t.container_id IS DISTINCT FROM r.new_container_id
           OR t.parent_id IS DISTINCT FROM r.new_parent_id)
    """
)


async def _resolve_container_parents(session: AsyncSession, source: str) -> None:
    await session.execute(_RESOLVE_CONTAINER_PARENTS, {"source": source})


async def _resolve_task_links(session: AsyncSession, source: str) -> None:
    await session.execute(_RESOLVE_TASK_LINKS, {"source": source})


_MARK_DELETED = {
    table: text(
        f"""
        UPDATE {table} SET deleted_at = now()
        WHERE source = :source AND deleted_at IS NULL AND NOT (external_id = ANY(:seen))
        """
    ).bindparams(bindparam("seen", type_=_TEXT_ARRAY))
    for table in ("containers", "tasks")
}


async def _mark_deleted(session: AsyncSession, table: str, source: str, seen: set[str]) -> int:
    """Soft delete dos registros da fonte que não estão em `seen`. Devolve quantos."""
    result = await session.execute(_MARK_DELETED[table], {"source": source, "seen": sorted(seen)})
    return result.rowcount or 0


async def _save_state(
    session: AsyncSession, source: str, watermark: datetime | None, last_full_sync_at: datetime | None
) -> None:
    """Upsert de `sync_state` (tarefas). `updated_at` vai explícito: o `onupdate`
    do modelo não vale para `ON CONFLICT DO UPDATE`."""
    values: dict[str, Any] = {"watermark": watermark}
    if last_full_sync_at is not None:
        values["last_full_sync_at"] = last_full_sync_at
    stmt = insert(SyncStateRow).values(source=source, resource=TASKS_RESOURCE, **values)
    stmt = stmt.on_conflict_do_update(
        index_elements=["source", "resource"], set_={**values, "updated_at": func.now()}
    )
    await session.execute(stmt)


async def _save_progress(session: AsyncSession, run_id: uuid.UUID, state: _RunState) -> None:
    await session.execute(update(SyncRunRow).where(SyncRunRow.id == run_id).values(stats=state.stats()))


# --- Erros e logs ---------------------------------------------------------------


def _describe(exc: BaseException) -> str:
    """Mensagem curta e segura. A de `ConnectorError` não traz credenciais (contrato
    do conector); de outras exceções (banco, bugs) só vai o tipo, porque a
    mensagem pode conter parâmetros SQL com conteúdo de tarefas."""
    if isinstance(exc, ConnectorError):
        return str(exc) or type(exc).__name__
    return f"erro interno ({type(exc).__name__})"


def _short(message: str) -> str:
    return message if len(message) <= ERROR_MAX_LEN else message[: ERROR_MAX_LEN - 1] + "…"


def _log_exception(prefix: str, exc: BaseException) -> None:
    """Loga tipo e pilha, sem a mensagem de exceções que não são do conector."""
    stack = "".join(traceback.format_tb(exc.__traceback__)).rstrip()
    logger.error("%s: %s\n%s", prefix, _describe(exc), stack)


__all__ = ["INTERRUPTED_ERROR", "ConnectorFactory", "SyncService"]
