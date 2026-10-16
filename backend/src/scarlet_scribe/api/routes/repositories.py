"""`GET /repositories` e `GET /repositories/{id}/avatar`: repositórios de código e o ícone."""

import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Response, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import defer

from scarlet_scribe.api.deps import PaginationDep, SessionDep
from scarlet_scribe.api.queries import like_pattern, paginate
from scarlet_scribe.api.schemas import ErrorDetail, RepositoryOut, RepositoryPage
from scarlet_scribe.db.models import RepositoryAvatarRow, RepositoryRow

router = APIRouter(tags=["repositories"])

# Tipos de imagem que a rota do ícone aceita servir (SVG fica de fora).
AVATAR_CONTENT_TYPES = frozenset(
    {
        "image/png",
        "image/jpeg",
        "image/gif",
        "image/webp",
        "image/bmp",
        "image/x-icon",
        "image/vnd.microsoft.icon",
    }
)


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
    avatar_updated_at = (
        select(RepositoryAvatarRow.fetched_at)
        .where(RepositoryAvatarRow.repository_id == RepositoryRow.id)
        .scalar_subquery()
    )
    stmt = select(RepositoryRow, avatar_updated_at.label("avatar_updated_at")).where(
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
    stmt = stmt.order_by(func.lower(RepositoryRow.path_with_namespace), RepositoryRow.id)
    rows, total = await paginate(
        session, stmt, page, options=[defer(RepositoryRow.raw)], entities=False
    )
    items = [
        RepositoryOut(
            id=r.id,
            name=r.name,
            path_with_namespace=r.path_with_namespace,
            web_url=r.web_url,
            default_branch=r.default_branch,
            archived=r.archived,
            last_activity_at=r.last_activity_at,
            avatar_updated_at=updated_at,
        )
        for r, updated_at in rows
    ]
    return RepositoryPage(items=items, total=total)


@router.get(
    "/repositories/{repository_id}/avatar",
    operation_id="get_repository_avatar",
    response_class=Response,
    responses={
        200: {
            "description": "Bytes do ícone, com o content-type guardado",
            "content": {"image/*": {"schema": {"type": "string", "format": "binary"}}},
        },
        404: {"model": ErrorDetail, "description": "Repositório inexistente, removido ou sem ícone"},
    },
)
async def get_repository_avatar(session: SessionDep, repository_id: uuid.UUID) -> Response:
    """Ícone do repositório, lido do banco (baixado no sync)."""
    avatar = await session.scalar(
        select(RepositoryAvatarRow)
        .join(RepositoryRow, RepositoryRow.id == RepositoryAvatarRow.repository_id)
        .where(RepositoryAvatarRow.repository_id == repository_id, RepositoryRow.deleted_at.is_(None))
    )
    if avatar is None or avatar.content_type not in AVATAR_CONTENT_TYPES:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Ícone não encontrado")
    return Response(
        content=avatar.data,
        media_type=avatar.content_type,
        headers={
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, max-age=86400",
            "Content-Security-Policy": "default-src 'none'; sandbox",
        },
    )
