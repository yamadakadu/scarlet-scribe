"""`GET /tasks` e `GET /tasks/{id}`."""

import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from scarlet_scribe.api.deps import PaginationDep, SessionDep
from scarlet_scribe.api.queries import (
    TASK_LOAD_OPTIONS,
    paginate,
    task_filters,
    task_order,
    task_out,
    task_ref,
)
from scarlet_scribe.api.schemas import (
    ErrorDetail,
    TaskDetail,
    TaskOrder,
    TaskPage,
    UtcDatetime,
    UtcDatetimeEnd,
)
from scarlet_scribe.db.models import TaskRow

router = APIRouter(tags=["tasks"])


@router.get("/tasks", response_model=TaskPage)
async def list_tasks(
    session: SessionDep,
    page: PaginationDep,
    container_id: Annotated[
        uuid.UUID | None,
        Query(description="Tarefas desse container e dos containers abaixo dele"),
    ] = None,
    status_: Annotated[
        list[str] | None,
        Query(
            alias="status",
            description="Nome do status, sem diferenciar maiúsculas; repita o parâmetro para vários",
        ),
    ] = None,
    assignee_id: Annotated[uuid.UUID | None, Query(description="Pessoa responsável")] = None,
    due_from: Annotated[
        UtcDatetime | None,
        Query(description="Prazo a partir deste instante (inclusive); uma data pura vale meia-noite UTC"),
    ] = None,
    due_to: Annotated[
        UtcDatetimeEnd | None,
        Query(
            description="Prazo até este instante (inclusive); "
            "uma data pura (AAAA-MM-DD) inclui o dia inteiro, até 23:59:59.999999 UTC"
        ),
    ] = None,
    is_milestone: Annotated[bool | None, Query(description="Só marcos (true) ou só não marcos (false)")] = None,
    include_closed: Annotated[
        bool, Query(description="Inclui as tarefas com status_type 'done' ou 'closed'")
    ] = False,
    archived: Annotated[
        bool,
        Query(description="false (padrão): só as tarefas ativas; true: só as arquivadas"),
    ] = False,
    q: Annotated[
        str | None, Query(description="Busca no nome, sem diferenciar maiúsculas")
    ] = None,
    order_by: Annotated[
        TaskOrder,
        Query(
            description="due_date (crescente, sem prazo no fim), "
            "updated_at (alteração na origem, mais recente primeiro) ou name"
        ),
    ] = TaskOrder.DUE_DATE,
) -> TaskPage:
    stmt = (
        select(TaskRow)
        .where(
            *task_filters(
                container_id=container_id,
                status=status_,
                assignee_id=assignee_id,
                due_from=due_from,
                due_to=due_to,
                is_milestone=is_milestone,
                include_closed=include_closed,
                archived=archived,
                q=q,
            )
        )
        .order_by(*task_order(order_by))
    )
    rows, total = await paginate(session, stmt, page, options=TASK_LOAD_OPTIONS)
    return TaskPage(items=[task_out(r) for r in rows], total=total)


@router.get(
    "/tasks/{task_id}",
    response_model=TaskDetail,
    responses={404: {"model": ErrorDetail, "description": "Tarefa inexistente"}},
)
async def get_task(session: SessionDep, task_id: uuid.UUID) -> TaskDetail:
    """Detalhe da tarefa, com assignees e subtarefas.

    Devolve a tarefa mesmo arquivada. As subtarefas incluem as encerradas e as
    arquivadas, cada uma com o seu `archived`.
    """
    row = await session.scalar(
        select(TaskRow)
        .where(TaskRow.id == task_id, TaskRow.deleted_at.is_(None))
        .options(*TASK_LOAD_OPTIONS)
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Tarefa não encontrada")
    subtasks = await session.scalars(
        select(TaskRow)
        .where(TaskRow.parent_id == row.id, TaskRow.deleted_at.is_(None))
        .order_by(*task_order(TaskOrder.DUE_DATE))
        .options(*TASK_LOAD_OPTIONS)
    )
    return TaskDetail(
        **task_out(row).model_dump(),
        parent=task_ref(row),
        subtasks=[task_out(s) for s in subtasks.all()],
    )
