"""Consultas compartilhadas pelos routers (paginação, filtros e serialização de tarefas).

Toda consulta filtra `deleted_at IS NULL`: registros removidos na origem
nunca aparecem nas respostas, nem como referência (assignee, container ou
tarefa-pai).
"""

import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import ColumnElement, Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer, selectinload

from scarlet_scribe.api.deps import Pagination
from scarlet_scribe.api.schemas import (
    ContainerRef,
    PersonOut,
    TaskOrder,
    TaskOut,
    TaskRef,
)
from scarlet_scribe.db.models import (
    ContainerRow,
    PersonRow,
    SyncRunRow,
    TaskRow,
    task_assignees,
)

# Categorias de status que contam como tarefa encerrada.
CLOSED_STATUS_TYPES = ("done", "closed")

# Ordem dos runs de sync, do mais recente para o mais antigo (o id desempata).
SYNC_RUNS_LATEST_FIRST = (SyncRunRow.requested_at.desc(), SyncRunRow.id.desc())


def like_pattern(text: str) -> str:
    """Padrão `%texto%` para ILIKE, com `%`, `_` e `\\` escapados."""
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


async def paginate(
    session: AsyncSession,
    stmt: Select[Any],
    page: Pagination,
    options: Sequence[Any] = (),
) -> tuple[list[Any], int]:
    """Executa `stmt` paginado e devolve `(itens, total sem paginação)`."""
    total = await session.scalar(
        select(func.count()).select_from(stmt.order_by(None).subquery())
    )
    rows = await session.scalars(
        stmt.options(*options).limit(page.limit).offset(page.offset)
    )
    return list(rows.all()), total or 0


def container_subtree_ids(container_id: uuid.UUID) -> Select[Any]:
    """Ids do container e de todos os descendentes vivos (CTE recursiva).

    Filtrar tarefas por um space ou folder traz as tarefas das lists abaixo
    dele. O `UNION` (sem `ALL`) garante término mesmo se houver um ciclo.
    """
    tree = (
        select(ContainerRow.id)
        .where(ContainerRow.id == container_id, ContainerRow.deleted_at.is_(None))
        .cte("container_tree", recursive=True)
    )
    tree = tree.union(
        select(ContainerRow.id).where(
            ContainerRow.parent_id == tree.c.id, ContainerRow.deleted_at.is_(None)
        )
    )
    return select(tree.c.id)


def task_filters(
    *,
    container_id: uuid.UUID | None = None,
    status: Sequence[str] | None = None,
    assignee_id: uuid.UUID | None = None,
    due_from: datetime | None = None,
    due_to: datetime | None = None,
    is_milestone: bool | None = None,
    include_closed: bool = False,
    q: str | None = None,
) -> list[ColumnElement[bool]]:
    conditions: list[ColumnElement[bool]] = [TaskRow.deleted_at.is_(None)]
    if container_id is not None:
        conditions.append(TaskRow.container_id.in_(container_subtree_ids(container_id)))
    # Valores vazios (`?status=`) são ignorados, em vez de não casarem com nada.
    wanted = [s.lower() for s in status or () if s.strip()]
    if wanted:
        conditions.append(func.lower(TaskRow.status).in_(wanted))
    if assignee_id is not None:
        conditions.append(
            TaskRow.id.in_(
                select(task_assignees.c.task_id)
                .join(PersonRow, PersonRow.id == task_assignees.c.person_id)
                .where(
                    task_assignees.c.person_id == assignee_id,
                    PersonRow.deleted_at.is_(None),
                )
            )
        )
    if due_from is not None:
        conditions.append(TaskRow.due_date >= due_from)
    if due_to is not None:
        conditions.append(TaskRow.due_date <= due_to)
    if is_milestone is not None:
        conditions.append(TaskRow.is_milestone.is_(is_milestone))
    if not include_closed:
        conditions.append(
            or_(
                TaskRow.status_type.is_(None),
                TaskRow.status_type.not_in(CLOSED_STATUS_TYPES),
            )
        )
    if q:
        conditions.append(TaskRow.name.ilike(like_pattern(q), escape="\\"))
    return conditions


def task_order(order_by: TaskOrder) -> list[Any]:
    match order_by:
        case TaskOrder.DUE_DATE:
            primary = TaskRow.due_date.asc().nulls_last()
        case TaskOrder.UPDATED_AT:
            primary = TaskRow.source_updated_at.desc().nulls_last()
        case TaskOrder.NAME:
            primary = func.lower(TaskRow.name).asc()
    return [primary, TaskRow.id]


# Carrega o necessário para `TaskOut` sem o `raw` (que pode ser grande).
TASK_LOAD_OPTIONS = (
    defer(TaskRow.raw),
    selectinload(TaskRow.container).load_only(
        ContainerRow.id, ContainerRow.kind, ContainerRow.name, ContainerRow.deleted_at
    ),
    selectinload(TaskRow.parent).load_only(
        TaskRow.id, TaskRow.name, TaskRow.deleted_at
    ),
    selectinload(TaskRow.assignees).load_only(
        PersonRow.id, PersonRow.username, PersonRow.email, PersonRow.deleted_at
    ),
)


def _live_parent(row: TaskRow) -> TaskRow | None:
    parent = row.parent
    return parent if parent is not None and parent.deleted_at is None else None


def task_out(row: TaskRow) -> TaskOut:
    container = row.container
    parent = _live_parent(row)
    return TaskOut(
        id=row.id,
        name=row.name,
        status=row.status,
        status_type=row.status_type,
        priority=row.priority,
        start_date=row.start_date,
        due_date=row.due_date,
        done_at=row.done_at,
        time_estimate_ms=row.time_estimate_ms,
        url=row.url,
        is_milestone=row.is_milestone,
        source_updated_at=row.source_updated_at,
        container=(
            ContainerRef.model_validate(container)
            if container is not None and container.deleted_at is None
            else None
        ),
        parent_id=parent.id if parent is not None else None,
        assignees=[
            PersonOut.model_validate(p)
            for p in sorted(row.assignees, key=lambda p: (p.username or "").lower())
            if p.deleted_at is None
        ],
    )


def task_ref(row: TaskRow) -> TaskRef | None:
    parent = _live_parent(row)
    return TaskRef.model_validate(parent) if parent is not None else None


__all__ = [
    "CLOSED_STATUS_TYPES",
    "SYNC_RUNS_LATEST_FIRST",
    "TASK_LOAD_OPTIONS",
    "container_subtree_ids",
    "like_pattern",
    "paginate",
    "task_filters",
    "task_order",
    "task_out",
    "task_ref",
]
