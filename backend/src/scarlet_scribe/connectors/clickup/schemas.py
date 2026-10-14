"""Modelos Pydantic do JSON da API v2 do ClickUp.

Uso restrito a `connectors/clickup/`: o resto do sistema só conhece os modelos
canônicos de `domain/`, produzidos pelo mapper.

Os modelos declaram apenas os campos que usamos. A API manda muito mais, e
`extra="allow"` preserva o restante (acessível por `model_dump()`), para que o
payload original possa ir para colunas `raw` sem nova requisição.

Datas e durações ficam em **milissegundos** (`int`), como vêm da API. A API
manda esses valores ora como string, ora como número; aqui ambos viram `int`.
A conversão para `datetime` UTC é trabalho do mapper.
"""

from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field


def _ms_or_none(value: Any) -> Any:
    """Normaliza um timestamp/duração em ms: string numérica vira int; vazio vira None."""
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return None
        return int(value)
    return value


def _str_id(value: Any) -> Any:
    """Ids que às vezes chegam como número passam a ser string."""
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    return value


Millis = Annotated[int | None, BeforeValidator(_ms_or_none)]
StrId = Annotated[str, BeforeValidator(_str_id)]


class ClickUpModel(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)


# --- Usuários e workspaces -------------------------------------------------


class ClickUpUser(ClickUpModel):
    """Usuário do ClickUp (dono do token, membro do team, assignee ou criador)."""

    id: int
    username: str | None = None
    email: str | None = None
    color: str | None = None
    initials: str | None = None
    profile_picture: str | None = Field(default=None, alias="profilePicture")


class ClickUpUserResponse(ClickUpModel):
    """Resposta de `GET /v2/user`."""

    user: ClickUpUser


class ClickUpTeamMember(ClickUpModel):
    user: ClickUpUser


class ClickUpTeam(ClickUpModel):
    """Workspace. Na API v2, "team" significa workspace."""

    id: StrId
    name: str
    color: str | None = None
    avatar: str | None = None
    members: list[ClickUpTeamMember] = Field(default_factory=list)


class ClickUpTeamsResponse(ClickUpModel):
    """Resposta de `GET /v2/team`."""

    teams: list[ClickUpTeam] = Field(default_factory=list)


# --- Hierarquia: space > folder > list -------------------------------------


class ClickUpRef(ClickUpModel):
    """Referência resumida a outro objeto (space, folder ou list) dentro de um payload.

    Nas lists fora de folder, `folder` vem como `{"id": ..., "name": "hidden", "hidden": true}`.
    """

    id: StrId
    name: str | None = None
    hidden: bool | None = None
    access: bool | None = None


class ClickUpSpace(ClickUpModel):
    id: StrId
    name: str
    private: bool | None = None
    archived: bool | None = None


class ClickUpSpacesResponse(ClickUpModel):
    """Resposta de `GET /v2/team/{team_id}/space`."""

    spaces: list[ClickUpSpace] = Field(default_factory=list)


class ClickUpFolder(ClickUpModel):
    id: StrId
    name: str
    orderindex: int | None = None
    hidden: bool | None = None
    archived: bool | None = None
    space: ClickUpRef | None = None
    # Subfolders vêm na mesma lista, sem aninhamento, com `parent_folder`.
    # O formato exato (id ou objeto) ainda não foi confirmado; aceitamos os dois.
    parent_folder: ClickUpRef | StrId | None = None

    @property
    def parent_folder_id(self) -> str | None:
        if isinstance(self.parent_folder, ClickUpRef):
            return self.parent_folder.id
        return self.parent_folder


class ClickUpFoldersResponse(ClickUpModel):
    """Resposta de `GET /v2/space/{space_id}/folder`."""

    folders: list[ClickUpFolder] = Field(default_factory=list)


class ClickUpList(ClickUpModel):
    id: StrId
    name: str
    orderindex: int | None = None
    archived: bool | None = None
    folder: ClickUpRef | None = None
    space: ClickUpRef | None = None


class ClickUpListsResponse(ClickUpModel):
    """Resposta de `GET /v2/folder/{folder_id}/list` e `GET /v2/space/{space_id}/list`."""

    lists: list[ClickUpList] = Field(default_factory=list)


# --- Tarefas ---------------------------------------------------------------


class ClickUpStatus(ClickUpModel):
    status: str
    type: str | None = None
    color: str | None = None
    orderindex: int | None = None


class ClickUpPriority(ClickUpModel):
    id: StrId | None = None
    priority: str | None = None
    color: str | None = None
    orderindex: StrId | None = None


class ClickUpTask(ClickUpModel):
    id: StrId
    custom_id: str | None = None
    name: str
    status: ClickUpStatus | None = None
    priority: ClickUpPriority | None = None
    assignees: list[ClickUpUser] = Field(default_factory=list)
    creator: ClickUpUser | None = None
    # Id da tarefa-pai quando é subtarefa.
    parent: StrId | None = None
    # 0 = tarefa comum, 1 = marco, outros = tipos customizados.
    custom_item_id: int | None = None
    archived: bool | None = None
    url: str | None = None
    team_id: StrId | None = None
    # `list_` para não sombrear o builtin; no JSON o campo é `list`.
    list_: ClickUpRef | None = Field(default=None, alias="list")
    folder: ClickUpRef | None = None
    space: ClickUpRef | None = None
    # Datas e durações em ms.
    date_created: Millis = None
    date_updated: Millis = None
    date_closed: Millis = None
    date_done: Millis = None
    start_date: Millis = None
    due_date: Millis = None
    time_estimate: Millis = None


class ClickUpTasksPage(ClickUpModel):
    """Uma página de `GET /v2/team/{team_id}/task` (não tem `last_page`)."""

    tasks: list[ClickUpTask] = Field(default_factory=list)
