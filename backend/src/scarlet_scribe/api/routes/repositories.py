"""`GET /repositories`: repositórios de código."""

from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import defer

from scarlet_scribe.api.deps import PaginationDep, SessionDep
from scarlet_scribe.api.queries import like_pattern, paginate
from scarlet_scribe.api.schemas import RepositoryOut, RepositoryPage
from scarlet_scribe.db.models import RepositoryRow

router = APIRouter(tags=["repositories"])


@router.get("/repositories", response_model=RepositoryPage)
async def list_repositories(
    session: SessionDep,
    page: PaginationDep,
    q: Annotated[
        str | None,
        Query(description="Busca no nome ou no caminho completo, sem diferenciar maiúsculas"),
    ] = None,
    archived: Annotated[
        bool, Query(description="false (padrão) traz só os ativos; true, só os arquivados")
    ] = False,
) -> RepositoryPage:
    stmt = select(RepositoryRow).where(
        RepositoryRow.deleted_at.is_(None), RepositoryRow.archived.is_(archived)
    )
    if q:
        pattern = like_pattern(q)
        stmt = stmt.where(
            or_(
                RepositoryRow.name.ilike(pattern, escape="\\"),
                RepositoryRow.path_with_namespace.ilike(pattern, escape="\\"),
            )
        )
    stmt = stmt.order_by(RepositoryRow.path_with_namespace, RepositoryRow.id)
    rows, total = await paginate(session, stmt, page, options=[defer(RepositoryRow.raw)])
    return RepositoryPage(items=[RepositoryOut.model_validate(r) for r in rows], total=total)
