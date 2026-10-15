"""Modelos de request e response da API (`/api/v1`).

A API expõe só os UUIDs internos; o id da ferramenta de origem nunca é
chave. Todos os instantes saem em ISO 8601 UTC (sufixo `Z`).
"""

import re
import uuid
from datetime import UTC, date, datetime, time
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel, BeforeValidator, ConfigDict, Field

from scarlet_scribe.domain.models import ContainerKind, MergeRequestState
from scarlet_scribe.domain.sync import SyncStatus, SyncTrigger


def _to_utc(value: datetime) -> datetime:
    """Converte para UTC; um instante sem fuso é tomado como UTC."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


UtcDatetime = Annotated[datetime, AfterValidator(_to_utc)]

_DATE_ONLY = re.compile(r"\d{4}-\d{2}-\d{2}")


def _end_of_day_if_date(value: object) -> object:
    """Uma data pura (`AAAA-MM-DD`) vale até o último instante do dia, em UTC."""
    if isinstance(value, str) and _DATE_ONLY.fullmatch(value.strip()):
        return datetime.combine(date.fromisoformat(value.strip()), time.max, tzinfo=UTC)
    return value


# Fim de intervalo inclusivo: uma data com hora vale como veio; uma data pura
# cobre o dia inteiro (até 23:59:59.999999 UTC). O início (`due_from`) usa
# `UtcDatetime`, em que uma data pura vale meia-noite.
UtcDatetimeEnd = Annotated[UtcDatetime, BeforeValidator(_end_of_day_if_date)]


class ApiModel(BaseModel):
    # Campos com valor padrão saem como obrigatórios no schema de resposta,
    # porque a resposta sempre os traz (o cliente TS não os gera como opcionais).
    model_config = ConfigDict(from_attributes=True, json_schema_serialization_defaults_required=True)


# --- Erros ---------------------------------------------------------------------


class ErrorDetail(ApiModel):
    """Erro no formato padrão do FastAPI (por exemplo 404, 429 e 503)."""

    detail: str


# --- Paginação ---------------------------------------------------------------


class Page[T](ApiModel):
    items: list[T]
    total: int = Field(description="Total de registros que atendem aos filtros, sem paginação")


# --- Health ------------------------------------------------------------------


class SyncRunOut(ApiModel):
    id: uuid.UUID
    trigger: SyncTrigger
    status: SyncStatus
    requested_at: UtcDatetime
    started_at: UtcDatetime | None
    finished_at: UtcDatetime | None
    stats: dict[str, Any] = Field(description="Contadores por entidade (criados, atualizados, removidos)")
    error: str | None


class SyncRunPage(Page[SyncRunOut]):
    pass


class HealthOut(ApiModel):
    status: Literal["ok", "error"] = Field(description="'ok' se a API e o banco respondem")
    database: Literal["ok", "error"]
    latest_sync: SyncRunOut | None = Field(
        description="Run de sync mais recente; nulo se nunca houve um ou se o banco não respondeu"
    )


# --- Projetos (containers) -----------------------------------------------------


class ProjectNode(ApiModel):
    id: uuid.UUID
    kind: ContainerKind
    name: str
    workspace_id: uuid.UUID
    parent_id: uuid.UUID | None = Field(
        description="Container pai; nulo no nível mais alto ou se o pai não está no banco"
    )
    children: list["ProjectNode"]


class ProjectTree(Page[ProjectNode]):
    """Árvore sem paginação; `total` é o número de nós no primeiro nível de `items`."""


# --- Pessoas -------------------------------------------------------------------


class PersonOut(ApiModel):
    id: uuid.UUID
    username: str | None
    email: str | None


class PersonPage(Page[PersonOut]):
    pass


# --- Tarefas -------------------------------------------------------------------


class TaskOrder(StrEnum):
    DUE_DATE = "due_date"
    UPDATED_AT = "updated_at"
    NAME = "name"


class ContainerRef(ApiModel):
    id: uuid.UUID
    kind: ContainerKind
    name: str


class TaskRef(ApiModel):
    id: uuid.UUID
    name: str
    archived: bool


class TaskOut(ApiModel):
    id: uuid.UUID
    name: str
    status: str | None
    status_type: str | None = Field(
        description="Categoria do status: 'open', 'custom', 'done' ou 'closed'"
    )
    priority: str | None
    start_date: UtcDatetime | None
    due_date: UtcDatetime | None
    done_at: UtcDatetime | None
    time_estimate_ms: int | None
    url: str | None
    is_milestone: bool
    archived: bool = Field(description="Arquivada na origem")
    source_updated_at: UtcDatetime | None = Field(
        description="Última alteração na origem (usada por order_by=updated_at)"
    )
    container: ContainerRef | None = Field(
        description="List da tarefa; nulo quando ela não está no banco (\"sem projeto\")"
    )
    parent_id: uuid.UUID | None = Field(description="Tarefa-pai, se for subtarefa")
    assignees: list[PersonOut]


class TaskPage(Page[TaskOut]):
    pass


class TaskDetail(TaskOut):
    parent: TaskRef | None
    subtasks: list[TaskOut]


# --- Fontes e repositórios de código --------------------------------------------


class SourceOut(ApiModel):
    id: Literal["clickup", "gitlab"]
    name: str
    enabled: bool = Field(description="Fonte configurada no servidor (token e escopo preenchidos)")
    last_synced_at: UtcDatetime | None = Field(
        description="Maior synced_at das linhas da fonte; nulo se nada foi sincronizado"
    )


class SourcePage(Page[SourceOut]):
    pass


class RepositoryOut(ApiModel):
    id: uuid.UUID
    name: str
    path_with_namespace: str
    web_url: str | None
    default_branch: str | None
    archived: bool
    last_activity_at: UtcDatetime | None


class RepositoryPage(Page[RepositoryOut]):
    pass


class RepositoryRef(ApiModel):
    id: uuid.UUID
    name: str
    path_with_namespace: str


class MergeRequestAuthor(ApiModel):
    id: uuid.UUID
    username: str | None


class MergeRequestOut(ApiModel):
    id: uuid.UUID
    iid: int
    title: str
    state: MergeRequestState
    draft: bool
    source_branch: str | None
    target_branch: str | None
    web_url: str | None
    created_at_source: UtcDatetime | None
    merged_at: UtcDatetime | None
    closed_at: UtcDatetime | None
    source_updated_at: UtcDatetime | None
    repository: RepositoryRef
    author: MergeRequestAuthor | None


class MergeRequestPage(Page[MergeRequestOut]):
    pass


class CommitOut(ApiModel):
    id: uuid.UUID
    sha: str
    short_sha: str | None
    title: str
    author_name: str | None
    authored_at: UtcDatetime | None
    committed_at: UtcDatetime | None
    web_url: str | None
    repository: RepositoryRef


class CommitPage(Page[CommitOut]):
    pass
