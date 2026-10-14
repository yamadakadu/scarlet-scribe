"""Funções puras ClickUp → modelos canônicos de `domain/`.

Regras (ver `ARCHITECTURE.md` › "Mapeamento ClickUp → modelo canônico"):

- Datas em ms viram `datetime` UTC; `None` e vazio viram `None`. Um valor que
  não converte levanta `MappingError` (o conector descarta só aquela tarefa).
- Todo id de **container** leva o nível como prefixo (`space:<id>`,
  `folder:<id>`, `list:<id>`), também em `external_parent_id` e em
  `Task.external_container_id`. Ids de tarefa e de pessoa não levam prefixo.
- Árvore: space é raiz; folder tem como pai o `parent_folder` ou, sem ele, o
  space; list em folder tem como pai a folder; list fora de folder (vinda de
  `GET /space/{id}/list`, `folderless=True`) tem como pai o space, seja qual
  for o `folder` do payload. O container de uma tarefa é sempre a list (a
  `folder` de uma tarefa com `hidden = true` não é uma folder de verdade).
- `Task.archived` é `True` se a tarefa veio da busca com `archived=true`
  (filtro de "só arquivadas") **ou** se o payload traz `archived: true`. O
  payload não desmarca: `archived: false` numa tarefa da busca de arquivadas
  continua `True`, porque o filtro da busca é o dado confirmado no spike.
- `raw` = `model_dump(by_alias=True, mode="json", exclude_unset=True)` do
  schema: nomes do JSON, extras incluídos, sem campos que não vieram. Só entra
  o payload do registro; nada de headers nem de credenciais.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from scarlet_scribe.connectors.clickup.schemas import (
    ClickUpFolder,
    ClickUpList,
    ClickUpModel,
    ClickUpSpace,
    ClickUpTask,
    ClickUpTeam,
    ClickUpUser,
)
from scarlet_scribe.domain.models import (
    Container,
    ContainerKind,
    Person,
    Task,
    Workspace,
)

SOURCE = "clickup"
# `custom_item_id` dos marcos (0 = tarefa comum, outros = tipos customizados).
MILESTONE_CUSTOM_ITEM_ID = 1

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


class MappingError(ValueError):
    """Um campo não pôde ser convertido. A mensagem traz o campo, nunca o valor."""

    def __init__(self, field: str, reason: str) -> None:
        super().__init__(f"{field}: {reason}")
        self.field = field
        self.reason = reason


# --- Conversões básicas ------------------------------------------------------


def ms_to_datetime(value: int | str | None, *, field: str = "data") -> datetime | None:
    """Unix em ms → `datetime` UTC. `None` e string vazia viram `None`."""
    if value is None:
        return None
    if isinstance(value, bool):
        raise MappingError(field, "tipo inválido")
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return None
        try:
            value = int(value)
        except ValueError:
            raise MappingError(field, "não é um número") from None
    if not isinstance(value, int):
        raise MappingError(field, "tipo inválido")
    try:
        return _EPOCH + timedelta(milliseconds=value)
    except OverflowError:
        raise MappingError(field, "fora do intervalo de datas") from None


def datetime_to_ms(value: datetime) -> int:
    """`datetime` com fuso → Unix em ms (para `date_updated_gt`)."""
    if value.tzinfo is None:
        raise ValueError("o datetime precisa ter fuso (UTC)")
    return int(value.timestamp() * 1000)


def container_id(kind: ContainerKind, raw_id: str) -> str:
    """Id canônico de container: o nível como prefixo (`space:123`)."""
    return f"{kind.value}:{raw_id}"


def space_ref(space_id: str) -> str:
    return container_id(ContainerKind.SPACE, space_id)


def folder_ref(folder_id: str) -> str:
    return container_id(ContainerKind.FOLDER, folder_id)


def list_ref(list_id: str) -> str:
    return container_id(ContainerKind.LIST, list_id)


def raw_payload(model: ClickUpModel) -> dict[str, Any]:
    """`raw` de um registro: o payload do schema, com os nomes e extras do JSON."""
    return model.model_dump(by_alias=True, mode="json", exclude_unset=True)


# --- Workspace e pessoas -----------------------------------------------------


def map_workspace(team: ClickUpTeam) -> Workspace:
    """Workspace (team na API v2)."""
    return Workspace(source=SOURCE, external_id=team.id, name=team.name, raw=raw_payload(team))


def map_person(user: ClickUpUser) -> Person:
    """Pessoa a partir de um usuário (member do team ou assignee de uma tarefa)."""
    return Person(
        source=SOURCE,
        external_id=str(user.id),
        username=user.username,
        email=user.email,
        raw=raw_payload(user),
    )


def map_members(team: ClickUpTeam) -> list[Person]:
    """Pessoas a partir de `members[].user` de `GET /v2/team`, sem repetir ids."""
    people: dict[str, Person] = {}
    for member in team.members:
        person = map_person(member.user)
        people.setdefault(person.external_id, person)
    return list(people.values())


# --- Containers --------------------------------------------------------------


def map_space(space: ClickUpSpace, *, workspace_id: str) -> Container:
    """Space: raiz da árvore."""
    return Container(
        source=SOURCE,
        external_id=space_ref(space.id),
        kind=ContainerKind.SPACE,
        name=space.name,
        external_workspace_id=workspace_id,
        external_parent_id=None,
        raw=raw_payload(space),
    )


def map_folder(folder: ClickUpFolder, *, workspace_id: str, space_id: str | None = None) -> Container:
    """Folder: pai é o `parent_folder` (ausente, id ou objeto) ou, sem ele, o space.

    `space_id` é o space que está sendo percorrido; sem ele, usa `folder.space`.
    """
    parent_folder_id = folder.parent_folder_id
    if parent_folder_id:
        parent = folder_ref(parent_folder_id)
    else:
        owner_space = space_id or (folder.space.id if folder.space else None)
        if owner_space is None:
            raise MappingError("space", "folder sem space")
        parent = space_ref(owner_space)
    return Container(
        source=SOURCE,
        external_id=folder_ref(folder.id),
        kind=ContainerKind.FOLDER,
        name=folder.name,
        external_workspace_id=workspace_id,
        external_parent_id=parent,
        raw=raw_payload(folder),
    )


def map_list(
    lst: ClickUpList,
    *,
    workspace_id: str,
    space_id: str | None = None,
    folder_id: str | None = None,
    folderless: bool = False,
) -> Container:
    """List: pai é a folder (list em folder) ou o space (list fora de folder).

    - `folderless=True`: a list veio de `GET /space/{id}/list` (fora de folder).
      O pai é o space, e `lst.folder` é ignorado (com ou sem `hidden`).
    - `folder_id`: a folder que está sendo percorrida (`GET /folder/{id}/list`).
    - Sem nenhum dos dois, usa `lst.folder`, desde que não seja a folder oculta
      (`hidden = true`) das lists fora de folder; nesse caso, o pai é o space.
    """
    if folderless and folder_id is not None:
        raise ValueError("folderless=True não combina com folder_id")
    if not folderless and folder_id is None and lst.folder is not None and not lst.folder.hidden:
        folder_id = lst.folder.id
    if folder_id:
        parent = folder_ref(folder_id)
    else:
        owner_space = space_id or (lst.space.id if lst.space else None)
        if owner_space is None:
            raise MappingError("space", "list sem space nem folder")
        parent = space_ref(owner_space)
    return Container(
        source=SOURCE,
        external_id=list_ref(lst.id),
        kind=ContainerKind.LIST,
        name=lst.name,
        external_workspace_id=workspace_id,
        external_parent_id=parent,
        raw=raw_payload(lst),
    )


# --- Tarefas -----------------------------------------------------------------


def is_milestone(task: ClickUpTask) -> bool:
    return task.custom_item_id == MILESTONE_CUSTOM_ITEM_ID


def map_task(task: ClickUpTask, *, archived: bool = False) -> Task:
    """Tarefa canônica. Levanta `MappingError` se uma data não converter.

    - `archived=True`: a tarefa veio da busca com `archived=true`. O resultado
      é `archived or task.archived` (ver a regra no topo do módulo).
    - O container é sempre a list (`list:<id>`), nunca a `folder` da tarefa.
    - `priority` vira o rótulo (`urgent`, `high`...) ou `None`.
    - `status_type` é repassado como vem (`open`, `custom`, `done`, `closed`...).
    - Os assignees viram `Person` com os dados da própria tarefa, inclusive os
      que não estão nos members do team.
    """
    priority = task.priority.priority if task.priority is not None else None
    return Task(
        source=SOURCE,
        external_id=task.id,
        name=task.name,
        status=task.status.status if task.status is not None else None,
        status_type=task.status.type if task.status is not None else None,
        priority=priority or None,
        start_date=ms_to_datetime(task.start_date, field="start_date"),
        due_date=ms_to_datetime(task.due_date, field="due_date"),
        done_at=ms_to_datetime(task.date_done, field="date_done"),
        time_estimate_ms=task.time_estimate,
        url=task.url,
        is_milestone=is_milestone(task),
        archived=archived or task.archived is True,
        source_updated_at=ms_to_datetime(task.date_updated, field="date_updated"),
        external_container_id=list_ref(task.list_.id) if task.list_ is not None else None,
        external_parent_id=task.parent or None,
        assignees=_unique_people(task.assignees),
        raw=raw_payload(task),
    )


def _unique_people(users: list[ClickUpUser]) -> list[Person]:
    people: dict[str, Person] = {}
    for user in users:
        person = map_person(user)
        people.setdefault(person.external_id, person)
    return list(people.values())


__all__ = [
    "MILESTONE_CUSTOM_ITEM_ID",
    "SOURCE",
    "MappingError",
    "container_id",
    "datetime_to_ms",
    "folder_ref",
    "is_milestone",
    "list_ref",
    "map_folder",
    "map_list",
    "map_members",
    "map_person",
    "map_space",
    "map_task",
    "map_workspace",
    "ms_to_datetime",
    "raw_payload",
    "space_ref",
]
