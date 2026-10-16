"""`GET /commits`: commits (sem o e-mail do autor)."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import aggregate_order_by
from sqlalchemy.orm import contains_eager, defer

from scarlet_scribe.api.deps import PaginationDep, SessionDep
from scarlet_scribe.api.queries import like_pattern, paginate
from scarlet_scribe.api.schemas import CommitOut, CommitPage, RepositoryRef, UtcDatetime, UtcDatetimeEnd
from scarlet_scribe.db.models import CommitRow, RepositoryRow, RepositoryTagRow

router = APIRouter(tags=["commits"])


@router.get("/commits", response_model=CommitPage)
async def list_commits(
    session: SessionDep,
    page: PaginationDep,
    repository_id: Annotated[uuid.UUID | None, Query(description="Repositório")] = None,
    from_: Annotated[
        UtcDatetime | None,
        Query(
            alias="from",
            description="Criado a partir deste instante (inclusive); uma data pura vale meia-noite UTC",
        ),
    ] = None,
    to: Annotated[
        UtcDatetimeEnd | None,
        Query(
            description="Criado até este instante (inclusive); "
            "uma data pura (AAAA-MM-DD) inclui o dia inteiro, até 23:59:59.999999 UTC"
        ),
    ] = None,
    q: Annotated[
        str | None, Query(description="Busca no título, sem diferenciar maiúsculas")
    ] = None,
) -> CommitPage:
    """Filtros de data sobre `authored_at`; mais recentes primeiro, sem data no fim."""
    tags = (
        select(func.array_agg(aggregate_order_by(RepositoryTagRow.name, RepositoryTagRow.name)))
        .where(
            RepositoryTagRow.repository_id == CommitRow.repository_id,
            RepositoryTagRow.commit_sha == CommitRow.sha,
            RepositoryTagRow.deleted_at.is_(None),
        )
        .scalar_subquery()
    )
    stmt = (
        select(CommitRow, tags.label("tags"))
        .join(CommitRow.repository)
        .where(CommitRow.deleted_at.is_(None), RepositoryRow.deleted_at.is_(None))
    )
    if repository_id is not None:
        stmt = stmt.where(CommitRow.repository_id == repository_id)
    if from_ is not None:
        stmt = stmt.where(CommitRow.authored_at >= from_)
    if to is not None:
        stmt = stmt.where(CommitRow.authored_at <= to)
    if q:
        stmt = stmt.where(CommitRow.title.ilike(like_pattern(q), escape="\\"))
    stmt = stmt.order_by(CommitRow.authored_at.desc().nulls_last(), CommitRow.id)
    rows, total = await paginate(
        session,
        stmt,
        page,
        options=[
            defer(CommitRow.raw),
            contains_eager(CommitRow.repository).load_only(
                RepositoryRow.id, RepositoryRow.name, RepositoryRow.path_with_namespace
            ),
        ],
        entities=False,
    )
    items = [
        CommitOut(
            id=r.id,
            sha=r.sha,
            short_sha=r.short_sha,
            title=r.title,
            author_name=r.author_name,
            authored_at=r.authored_at,
            committed_at=r.committed_at,
            web_url=r.web_url,
            repository=RepositoryRef.model_validate(r.repository),
            tags=tag_names or [],
        )
        for r, tag_names in rows
    ]
    return CommitPage(items=items, total=total)
