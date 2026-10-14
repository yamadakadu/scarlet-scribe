"""Tabelas da Fase 1 (SQLAlchemy 2, estilo `Mapped`).

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
    String,
    Table,
    Text,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from scarlet_scribe.db.base import Base, SyncedMixin, text_enum
from scarlet_scribe.domain.models import ContainerKind
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
