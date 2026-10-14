"""`GET /people`: membros do workspace."""

from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import defer

from scarlet_scribe.api.deps import PaginationDep, SessionDep
from scarlet_scribe.api.queries import like_pattern, paginate
from scarlet_scribe.api.schemas import PersonOut, PersonPage
from scarlet_scribe.db.models import PersonRow

router = APIRouter(tags=["people"])


@router.get("/people", response_model=PersonPage)
async def list_people(
    session: SessionDep,
    page: PaginationDep,
    q: Annotated[
        str | None,
        Query(description="Busca no nome de usuário ou no e-mail, sem diferenciar maiúsculas"),
    ] = None,
) -> PersonPage:
    stmt = select(PersonRow).where(PersonRow.deleted_at.is_(None))
    if q:
        pattern = like_pattern(q)
        stmt = stmt.where(
            or_(
                PersonRow.username.ilike(pattern, escape="\\"),
                PersonRow.email.ilike(pattern, escape="\\"),
            )
        )
    stmt = stmt.order_by(func.lower(PersonRow.username).asc().nulls_last(), PersonRow.id)
    rows, total = await paginate(session, stmt, page, options=[defer(PersonRow.raw)])
    return PersonPage(items=[PersonOut.model_validate(r) for r in rows], total=total)
