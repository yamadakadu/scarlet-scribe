"""Tabelas da Fase 1 e da Fase M, o GitLab (SQLAlchemy 2, estilo `Mapped`).

As tabelas sincronizadas herdam `SyncedMixin` (ver `db/base.py`). As da
Fase 2 entram numa migration própria e não são declaradas aqui.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Column,
    ForeignKey,
    Index,
    LargeBinary,
    String,
    Table,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from scarlet_scribe.db.base import Base, SyncedMixin, text_enum
from scarlet_scribe.domain.models import ContainerKind, IssueState, MergeRequestState
from scarlet_scribe.domain.sync import SyncStatus, SyncTrigger


class WorkspaceRow(SyncedMixin, Base):
    __tablename__ = "workspaces"

    name: Mapped[str] = mapped_column(Text)

    containers: Mapped[list["ContainerRow"]] = relationship(back_populates="workspace")


class ContainerRow(SyncedMixin, Base):
    """Space, folder ou list, numa única árvore (`parent_id`).

    `external_id` e `external_parent_id` levam o nível como prefixo
    (`space:123`, `folder:456`, `list:789`), porque a origem não garante ids
    distintos entre níveis. `parent_id` aceita nulo e é preenchido pelo sync a
    partir de `external_parent_id`, com o mesmo `UPDATE` usado em `tasks`.
    """

    __tablename__ = "containers"

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"))
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("containers.id", ondelete="SET NULL")
    )
    external_parent_id: Mapped[str | None] = mapped_column(Text)
    kind: Mapped[ContainerKind] = mapped_column(text_enum(ContainerKind, "kind"))
    name: Mapped[str] = mapped_column(Text)

    workspace: Mapped[WorkspaceRow] = relationship(back_populates="containers")
    parent: Mapped["ContainerRow | None"] = relationship(
        back_populates="children", remote_side="ContainerRow.id"
    )
    children: Mapped[list["ContainerRow"]] = relationship(back_populates="parent")
    tasks: Mapped[list["TaskRow"]] = relationship(back_populates="container")


class PersonRow(SyncedMixin, Base):
    __tablename__ = "people"

    username: Mapped[str | None] = mapped_column(Text)
    email: Mapped[str | None] = mapped_column(Text)

    tasks: Mapped[list["TaskRow"]] = relationship(
        secondary="task_assignees", back_populates="assignees"
    )


task_assignees = Table(
    "task_assignees",
    Base.metadata,
    Column(
        "task_id",
        ForeignKey("tasks.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "person_id",
        ForeignKey("people.id", ondelete="CASCADE"),
        primary_key=True,
        # A PK (task_id, person_id) não atende buscas só por person_id
        # (filtro assignee_id e o CASCADE a partir de people).
        index=True,
    ),
)


class TaskRow(SyncedMixin, Base):
    """Tarefa (inclusive marcos e subtarefas).

    `container_id` e `parent_id` aceitam nulo: o container ou a tarefa-pai
    podem não estar no banco. Os ids da origem ficam ao lado
    (`external_container_id`, `external_parent_id`) para o sync preencher as
    FKs depois, num único `UPDATE`. `external_container_id` leva o prefixo do
    nível, como o `external_id` de `containers` (por exemplo `list:789`).
    """

    __tablename__ = "tasks"

    name: Mapped[str] = mapped_column(Text)
    status: Mapped[str | None] = mapped_column(Text)
    status_type: Mapped[str | None] = mapped_column(Text)
    priority: Mapped[str | None] = mapped_column(Text)
    start_date: Mapped[datetime | None]
    due_date: Mapped[datetime | None] = mapped_column(index=True)
    done_at: Mapped[datetime | None]
    time_estimate_ms: Mapped[int | None] = mapped_column(BigInteger)
    url: Mapped[str | None] = mapped_column(Text)
    is_milestone: Mapped[bool] = mapped_column(server_default=text("false"), index=True)
    source_updated_at: Mapped[datetime | None]
    # Arquivada na origem. Sem índice de propósito: a listagem padrão
    # (`archived = false`) pega quase todas as linhas, e um índice nessa
    # coluna não seria usado pelo planner; a listagem das arquivadas é rara e
    # pequena. Ver a migration 0002.
    archived: Mapped[bool] = mapped_column(server_default=text("false"))

    container_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("containers.id", ondelete="SET NULL"), index=True
    )
    external_container_id: Mapped[str | None] = mapped_column(Text)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("tasks.id", ondelete="SET NULL"), index=True
    )
    external_parent_id: Mapped[str | None] = mapped_column(Text)

    container: Mapped[ContainerRow | None] = relationship(back_populates="tasks")
    parent: Mapped["TaskRow | None"] = relationship(
        back_populates="subtasks", remote_side="TaskRow.id"
    )
    subtasks: Mapped[list["TaskRow"]] = relationship(back_populates="parent")
    assignees: Mapped[list[PersonRow]] = relationship(
        secondary=task_assignees, back_populates="tasks"
    )


class RepositoryRow(SyncedMixin, Base):
    """Repositório de código (projeto do GitLab)."""

    __tablename__ = "repositories"

    name: Mapped[str] = mapped_column(Text)
    path_with_namespace: Mapped[str] = mapped_column(Text)
    web_url: Mapped[str | None] = mapped_column(Text)
    default_branch: Mapped[str | None] = mapped_column(Text)
    archived: Mapped[bool] = mapped_column(server_default=text("false"))
    last_activity_at: Mapped[datetime | None]
    avatar_url: Mapped[str | None] = mapped_column(Text)

    merge_requests: Mapped[list["MergeRequestRow"]] = relationship(
        back_populates="repository"
    )
    issues: Mapped[list["IssueRow"]] = relationship(back_populates="repository")
    commits: Mapped[list["CommitRow"]] = relationship(back_populates="repository")
    tags: Mapped[list["RepositoryTagRow"]] = relationship(back_populates="repository")
    avatar: Mapped["RepositoryAvatarRow | None"] = relationship(
        back_populates="repository", uselist=False
    )


class RepositoryAvatarRow(Base):
    """Ícone baixado no sync (bytes); a API serve daqui, sem chamar o GitLab."""

    __tablename__ = "repository_avatars"

    repository_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("repositories.id", ondelete="CASCADE"), primary_key=True
    )
    source_url: Mapped[str] = mapped_column(Text)
    content_type: Mapped[str] = mapped_column(Text)
    data: Mapped[bytes] = mapped_column(LargeBinary)
    fetched_at: Mapped[datetime]

    repository: Mapped[RepositoryRow] = relationship(back_populates="avatar")


class MergeRequestRow(SyncedMixin, Base):
    """Merge request. `external_id` é o id global; `iid` é o número no repositório.

    `author_id` aceita nulo e é preenchido pelo sync a partir de
    `external_author_id`, como `container_id` em `tasks`.
    """

    __tablename__ = "merge_requests"

    __table_args__ = (
        UniqueConstraint("source", "external_id"),
        UniqueConstraint("repository_id", "iid"),
    )

    repository_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("repositories.id"), index=True
    )
    iid: Mapped[int]
    title: Mapped[str] = mapped_column(Text)
    state: Mapped[MergeRequestState] = mapped_column(
        text_enum(MergeRequestState, "state")
    )
    draft: Mapped[bool] = mapped_column(server_default=text("false"))
    source_branch: Mapped[str | None] = mapped_column(Text)
    target_branch: Mapped[str | None] = mapped_column(Text)
    web_url: Mapped[str | None] = mapped_column(Text)
    author_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("people.id", ondelete="SET NULL"), index=True
    )
    external_author_id: Mapped[str | None] = mapped_column(Text)
    created_at_source: Mapped[datetime | None]
    merged_at: Mapped[datetime | None]
    closed_at: Mapped[datetime | None]
    source_updated_at: Mapped[datetime | None] = mapped_column(index=True)

    repository: Mapped[RepositoryRow] = relationship(back_populates="merge_requests")
    author: Mapped[PersonRow | None] = relationship()


class IssueRow(SyncedMixin, Base):
    """Issue. `external_id` é o id global; `iid` é o número no repositório.

    `author_id` aceita nulo e é preenchido pelo sync a partir de
    `external_author_id`, como nos merge requests. O `(repository_id, iid)`
    único já cobre as consultas por `repository_id`.
    """

    __tablename__ = "issues"

    __table_args__ = (
        UniqueConstraint("source", "external_id"),
        UniqueConstraint("repository_id", "iid"),
    )

    repository_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("repositories.id"))
    iid: Mapped[int]
    title: Mapped[str] = mapped_column(Text)
    state: Mapped[IssueState] = mapped_column(text_enum(IssueState, "state"))
    confidential: Mapped[bool] = mapped_column(server_default=text("false"))
    issue_type: Mapped[str | None] = mapped_column(Text)
    web_url: Mapped[str | None] = mapped_column(Text)
    author_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("people.id", ondelete="SET NULL"), index=True
    )
    external_author_id: Mapped[str | None] = mapped_column(Text)
    created_at_source: Mapped[datetime | None]
    closed_at: Mapped[datetime | None]
    source_updated_at: Mapped[datetime | None] = mapped_column(index=True)

    repository: Mapped[RepositoryRow] = relationship(back_populates="issues")
    author: Mapped[PersonRow | None] = relationship()


class CommitRow(SyncedMixin, Base):
    """Commit. `external_id` é '<id do projeto>:<sha>' (o mesmo sha existe em forks)."""

    __tablename__ = "commits"

    __table_args__ = (
        UniqueConstraint("source", "external_id"),
        UniqueConstraint("repository_id", "sha"),
        Index("ix_commits_repository_id_authored_at", "repository_id", "authored_at"),
    )

    repository_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("repositories.id"))
    sha: Mapped[str] = mapped_column(Text)
    short_sha: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    author_name: Mapped[str | None] = mapped_column(Text)
    author_email: Mapped[str | None] = mapped_column(Text)
    authored_at: Mapped[datetime | None]
    committed_at: Mapped[datetime | None]
    web_url: Mapped[str | None] = mapped_column(Text)

    repository: Mapped[RepositoryRow] = relationship(back_populates="commits")


class RepositoryTagRow(SyncedMixin, Base):
    """Tag de repositório. `external_id` é '<id do projeto>:<nome>'.

    `commit_sha` não tem FK para `commits` (o commit pode estar fora da janela).
    """

    __tablename__ = "repository_tags"

    __table_args__ = (
        UniqueConstraint("source", "external_id"),
        UniqueConstraint("repository_id", "name"),
        Index("ix_repository_tags_repository_id_commit_sha", "repository_id", "commit_sha"),
    )

    repository_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("repositories.id"))
    name: Mapped[str] = mapped_column(Text)
    commit_sha: Mapped[str] = mapped_column(Text)

    repository: Mapped[RepositoryRow] = relationship(back_populates="tags")


class SyncRunRow(Base):
    """Uma execução de sync; a tabela também é a fila do worker."""

    __tablename__ = "sync_runs"
    __table_args__ = (
        # No máximo um run `pending` ou `running` por vez. O índice é sobre a
        # constante `true`: toda linha ativa tem a mesma chave, então a
        # segunda inserção ativa viola a unicidade.
        Index(
            "uq_sync_runs_single_active",
            text("(true)"),
            unique=True,
            postgresql_where=text("status IN ('pending', 'running')"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=text("gen_random_uuid()")
    )
    trigger: Mapped[SyncTrigger] = mapped_column(text_enum(SyncTrigger, "trigger"))
    status: Mapped[SyncStatus] = mapped_column(
        text_enum(SyncStatus, "status"), server_default=SyncStatus.PENDING.value
    )
    requested_at: Mapped[datetime] = mapped_column(server_default=func.now())
    started_at: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]
    stats: Mapped[dict[str, Any]] = mapped_column(server_default=text("'{}'::jsonb"))
    error: Mapped[str | None] = mapped_column(Text)


class SyncStateRow(Base):
    """Watermark do sync por `(source, resource)`, por exemplo ('clickup', 'tasks')."""

    __tablename__ = "sync_state"

    source: Mapped[str] = mapped_column(String(32), primary_key=True)
    resource: Mapped[str] = mapped_column(String(64), primary_key=True)
    # Maior data de alteração na origem já vista (nas tarefas, o date_updated).
    watermark: Mapped[datetime | None]
    # Última listagem completa (reconciliação) concluída.
    last_full_sync_at: Mapped[datetime | None]
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now()
    )
