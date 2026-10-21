"""`GET /issues`: issues do GitLab."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import select
from sqlalchemy.orm import contains_eager, defer, selectinload

from scarlet_scribe.api.deps import PaginationDep, SessionDep
from scarlet_scribe.api.queries import like_pattern, paginate
from scarlet_scribe.api.schemas import (
    IssueOut,
    IssuePage,
    MergeRequestAuthor,
    RepositoryRef,
)
from scarlet_scribe.db.models import IssueRow, PersonRow, RepositoryRow
from scarlet_scribe.domain.models import IssueState

router = APIRouter(tags=["issues"])


@router.get("/issues", response_model=IssuePage)
async def list_issues(
    session: SessionDep,
    page: PaginationDep,
    repository_id: Annotated[uuid.UUID | None, Query(description="Repositório")] = None,
    state: Annotated[
        list[IssueState] | None,
        Query(description="Estado da issue; repita o parâmetro para vários"),
    ] = None,
    author_id: Annotated[uuid.UUID | None, Query(description="Pessoa autora")] = None,
    q: Annotated[
        str | None, Query(description="Busca no título, sem diferenciar maiúsculas")
    ] = None,
) -> IssuePage:
    """Mais recentemente alteradas primeiro.

    Issues confidenciais nunca saem (nem como indicador) e as de repositórios
    removidos ficam de fora.
    """
    stmt = (
        select(IssueRow)
        .join(IssueRow.repository)
        .where(
            IssueRow.deleted_at.is_(None),
            IssueRow.confidential.is_(False),
            RepositoryRow.deleted_at.is_(None),
        )
    )
    if repository_id is not None:
        stmt = stmt.where(IssueRow.repository_id == repository_id)
    if state:
        stmt = stmt.where(IssueRow.state.in_(state))
    if author_id is not None:
        stmt = stmt.where(
            IssueRow.author_id.in_(
                select(PersonRow.id).where(
                    PersonRow.id == author_id, PersonRow.deleted_at.is_(None)
                )
            )
        )
    if q:
        stmt = stmt.where(IssueRow.title.ilike(like_pattern(q), escape="\\"))
    stmt = stmt.order_by(IssueRow.source_updated_at.desc().nulls_last(), IssueRow.id)
    rows, total = await paginate(
        session,
        stmt,
        page,
        options=[
            defer(IssueRow.raw),
            contains_eager(IssueRow.repository).load_only(
                RepositoryRow.id, RepositoryRow.name, RepositoryRow.path_with_namespace
            ),
            selectinload(IssueRow.author).load_only(
                PersonRow.id, PersonRow.username, PersonRow.deleted_at
            ),
        ],
    )
    items = [
        IssueOut(
            id=r.id,
            iid=r.iid,
            title=r.title,
            state=r.state,
            issue_type=r.issue_type,
            web_url=r.web_url,
            created_at_source=r.created_at_source,
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
    return IssuePage(items=items, total=total)
