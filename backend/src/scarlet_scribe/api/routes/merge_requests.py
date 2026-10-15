"""`GET /merge-requests`: merge requests."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import select
from sqlalchemy.orm import contains_eager, defer, selectinload

from scarlet_scribe.api.deps import PaginationDep, SessionDep
from scarlet_scribe.api.queries import like_pattern, paginate
from scarlet_scribe.api.schemas import (
    MergeRequestAuthor,
    MergeRequestOut,
    MergeRequestPage,
    RepositoryRef,
    UtcDatetime,
)
from scarlet_scribe.db.models import MergeRequestRow, PersonRow, RepositoryRow
from scarlet_scribe.domain.models import MergeRequestState

router = APIRouter(tags=["merge-requests"])


@router.get("/merge-requests", response_model=MergeRequestPage)
async def list_merge_requests(
    session: SessionDep,
    page: PaginationDep,
    repository_id: Annotated[uuid.UUID | None, Query(description="Repositório")] = None,
    state: Annotated[
        list[MergeRequestState] | None,
        Query(description="Estado do MR; repita o parâmetro para vários"),
    ] = None,
    author_id: Annotated[uuid.UUID | None, Query(description="Pessoa autora")] = None,
    q: Annotated[
        str | None, Query(description="Busca no título, sem diferenciar maiúsculas")
    ] = None,
    updated_from: Annotated[
        UtcDatetime | None,
        Query(
            description="Alterado na origem a partir deste instante (inclusive); "
            "uma data pura vale meia-noite UTC"
        ),
    ] = None,
) -> MergeRequestPage:
    """Mais recentemente alterados primeiro. MRs de repositórios removidos ficam de fora."""
    stmt = (
        select(MergeRequestRow)
        .join(MergeRequestRow.repository)
        .where(MergeRequestRow.deleted_at.is_(None), RepositoryRow.deleted_at.is_(None))
    )
    if repository_id is not None:
        stmt = stmt.where(MergeRequestRow.repository_id == repository_id)
    if state:
        stmt = stmt.where(MergeRequestRow.state.in_(state))
    if author_id is not None:
        stmt = stmt.where(MergeRequestRow.author_id == author_id)
    if q:
        stmt = stmt.where(MergeRequestRow.title.ilike(like_pattern(q), escape="\\"))
    if updated_from is not None:
        stmt = stmt.where(MergeRequestRow.source_updated_at >= updated_from)
    stmt = stmt.order_by(
        MergeRequestRow.source_updated_at.desc().nulls_last(), MergeRequestRow.id
    )
    rows, total = await paginate(
        session,
        stmt,
        page,
        options=[
            defer(MergeRequestRow.raw),
            contains_eager(MergeRequestRow.repository).load_only(
                RepositoryRow.id, RepositoryRow.name, RepositoryRow.path_with_namespace
            ),
            selectinload(MergeRequestRow.author).load_only(
                PersonRow.id, PersonRow.username, PersonRow.deleted_at
            ),
        ],
    )
    items = [
        MergeRequestOut(
            id=r.id,
            iid=r.iid,
            title=r.title,
            state=r.state,
            draft=r.draft,
            source_branch=r.source_branch,
            target_branch=r.target_branch,
            web_url=r.web_url,
            created_at_source=r.created_at_source,
            merged_at=r.merged_at,
            closed_at=r.closed_at,
            source_updated_at=r.source_updated_at,
            repository=RepositoryRef.model_validate(r.repository),
            author=(
                MergeRequestAuthor.model_validate(r.author)
                if r.author is not None and r.author.deleted_at is None
                else None
            ),
        )
        for r in rows
    ]
    return MergeRequestPage(items=items, total=total)
