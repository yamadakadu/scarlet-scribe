"""`GET /projects`: árvore space/folder/list, sem paginação."""

import uuid
from collections.abc import Iterator
from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import select
from sqlalchemy.orm import load_only

from scarlet_scribe.api.deps import SessionDep
from scarlet_scribe.api.schemas import ProjectNode, ProjectTree
from scarlet_scribe.db.models import ContainerRow
from scarlet_scribe.domain.models import ContainerKind

router = APIRouter(tags=["projects"])

_KIND_ORDER = {ContainerKind.SPACE: 0, ContainerKind.FOLDER: 1, ContainerKind.LIST: 2}


def _sort(nodes: list[ProjectNode]) -> None:
    nodes.sort(key=lambda n: (_KIND_ORDER[n.kind], n.name.lower(), str(n.id)))
    for node in nodes:
        _sort(node.children)


def _walk(nodes: list[ProjectNode]) -> Iterator[ProjectNode]:
    for node in nodes:
        yield node
        yield from _walk(node.children)


@router.get("/projects", response_model=ProjectTree)
async def list_projects(
    session: SessionDep,
    kind: Annotated[
        ContainerKind | None,
        Query(description="Devolve os nós desse nível (cada um com a sua subárvore)"),
    ] = None,
    parent_id: Annotated[
        uuid.UUID | None,
        Query(description="Restringe à subárvore abaixo desse container"),
    ] = None,
) -> ProjectTree:
    """Árvore inteira, sem paginação.

    - Sem filtros: os nós de primeiro nível (spaces, e containers cujo pai não
      está no banco), cada um com os filhos aninhados em `children`.
    - `parent_id`: os filhos diretos desse container, com as subárvores.
    - `kind`: todos os nós daquele nível (dentro de `parent_id`, se houver),
      cada um com a sua subárvore.

    Um `parent_id` inexistente devolve a lista vazia.
    """
    rows = await session.scalars(
        select(ContainerRow)
        .where(ContainerRow.deleted_at.is_(None))
        .options(
            load_only(
                ContainerRow.id,
                ContainerRow.kind,
                ContainerRow.name,
                ContainerRow.workspace_id,
                ContainerRow.parent_id,
            )
        )
    )
    nodes: dict[uuid.UUID, ProjectNode] = {
        row.id: ProjectNode(
            id=row.id,
            kind=row.kind,
            name=row.name,
            workspace_id=row.workspace_id,
            parent_id=row.parent_id,
        )
        for row in rows.all()
    }
    roots: list[ProjectNode] = []
    for node in nodes.values():
        parent = nodes.get(node.parent_id) if node.parent_id is not None else None
        if parent is None:
            node.parent_id = None  # pai ausente ou removido: vira raiz
            roots.append(node)
        else:
            parent.children.append(node)
    _sort(roots)

    if parent_id is not None:
        scope = nodes[parent_id].children if parent_id in nodes else []
    else:
        scope = roots
    items = [n for n in _walk(scope) if n.kind == kind] if kind is not None else scope
    return ProjectTree(items=items, total=len(items))
