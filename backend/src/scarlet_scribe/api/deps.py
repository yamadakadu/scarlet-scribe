"""Dependências dos routers: sessão do banco, configuração e paginação.

Na Fase 2 entra aqui o `current_user`.
"""

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from scarlet_scribe.config import Settings, get_settings
from scarlet_scribe.db.session import get_session

MAX_PAGE_SIZE = 200
DEFAULT_PAGE_SIZE = 50

SessionDep = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


@dataclass(frozen=True, slots=True)
class Pagination:
    limit: int
    offset: int


def pagination(
    limit: Annotated[
        int, Query(ge=1, le=MAX_PAGE_SIZE, description="Itens por página (máximo 200)")
    ] = DEFAULT_PAGE_SIZE,
    offset: Annotated[int, Query(ge=0, description="Itens a pular")] = 0,
) -> Pagination:
    return Pagination(limit=limit, offset=offset)


PaginationDep = Annotated[Pagination, Depends(pagination)]
