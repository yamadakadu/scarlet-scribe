"""`GET /milestones`: atalho para `GET /tasks?is_milestone=true`, por prazo."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import select

from scarlet_scribe.api.deps import PaginationDep, SessionDep
from scarlet_scribe.api.queries import TASK_LOAD_OPTIONS, paginate, task_filters, task_order, task_out
from scarlet_scribe.api.schemas import TaskOrder, TaskPage, UtcDatetime
from scarlet_scribe.db.models import TaskRow

router = APIRouter(tags=["milestones"])


@router.get("/milestones", response_model=TaskPage)
async def list_milestones(
    session: SessionDep,
    page: PaginationDep,
    container_id: Annotated[
        uuid.UUID | None,
        Query(description="Marcos desse container e dos containers abaixo dele"),
    ] = None,
    due_from: Annotated[
        UtcDatetime | None, Query(description="Prazo a partir deste instante (inclusive)")
    ] = None,
    due_to: Annotated[
        UtcDatetime | None, Query(description="Prazo até este instante (inclusive)")
    ] = None,
) -> TaskPage:
    """Mesmos padrões de `GET /tasks`: marcos encerrados ficam de fora."""
    stmt = (
        select(TaskRow)
        .where(
            *task_filters(
                container_id=container_id,
                due_from=due_from,
                due_to=due_to,
                is_milestone=True,
            )
        )
        .order_by(*task_order(TaskOrder.DUE_DATE))
    )
    rows, total = await paginate(session, stmt, page, options=TASK_LOAD_OPTIONS)
    return TaskPage(items=[task_out(r) for r in rows], total=total)
