"""fase 1: tabelas iniciais

Workspaces, containers, people, tasks, task_assignees, sync_runs e sync_state.

Gerada por autogenerate e revisada à mão:
- `kind`, `trigger` e `status` são texto com CHECK (não há tipos enum do
  Postgres); o autogenerate duplicava cada CHECK e foi corrigido;
- o índice único parcial de `sync_runs` foi conferido no psql.

Revision ID: 0001
Revises:
Create Date: 2026-10-14 11:37:27.521160

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _synced_head() -> list[sa.Column]:
    """`id`, `source` e `external_id` de toda tabela sincronizada."""
    return [
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("external_id", sa.Text(), nullable=False),
    ]


def _synced_tail() -> list[sa.Column]:
    """`raw`, `synced_at` e `deleted_at` de toda tabela sincronizada."""
    return [
        sa.Column(
            "raw",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "synced_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    ]


def _synced_keys(table: str) -> list[sa.Constraint]:
    return [
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{table}")),
        sa.UniqueConstraint("source", "external_id", name=op.f(f"uq_{table}_source_external_id")),
    ]


def upgrade() -> None:
    op.create_table(
        "workspaces",
        *_synced_head(),
        sa.Column("name", sa.Text(), nullable=False),
        *_synced_tail(),
        *_synced_keys("workspaces"),
    )

    op.create_table(
        "containers",
        *_synced_head(),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("parent_id", sa.Uuid(), nullable=True),
        sa.Column("external_parent_id", sa.Text(), nullable=True),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        *_synced_tail(),
        *_synced_keys("containers"),
        sa.CheckConstraint(
            "kind IN ('space', 'folder', 'list')", name=op.f("ck_containers_kind")
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_containers_workspace_id_workspaces"),
        ),
        sa.ForeignKeyConstraint(
            ["parent_id"],
            ["containers.id"],
            name=op.f("fk_containers_parent_id_containers"),
            ondelete="SET NULL",
        ),
    )

    op.create_table(
        "people",
        *_synced_head(),
        sa.Column("username", sa.Text(), nullable=True),
        sa.Column("email", sa.Text(), nullable=True),
        *_synced_tail(),
        *_synced_keys("people"),
    )

    op.create_table(
        "tasks",
        *_synced_head(),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=True),
        sa.Column("status_type", sa.Text(), nullable=True),
        sa.Column("priority", sa.Text(), nullable=True),
        sa.Column("start_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("due_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("done_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("time_estimate_ms", sa.BigInteger(), nullable=True),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("is_milestone", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("container_id", sa.Uuid(), nullable=True),
        sa.Column("external_container_id", sa.Text(), nullable=True),
        sa.Column("parent_id", sa.Uuid(), nullable=True),
        sa.Column("external_parent_id", sa.Text(), nullable=True),
        *_synced_tail(),
        *_synced_keys("tasks"),
        sa.ForeignKeyConstraint(
            ["container_id"],
            ["containers.id"],
            name=op.f("fk_tasks_container_id_containers"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["parent_id"],
            ["tasks.id"],
            name=op.f("fk_tasks_parent_id_tasks"),
            ondelete="SET NULL",
        ),
    )
    op.create_index(op.f("ix_tasks_due_date"), "tasks", ["due_date"])
    op.create_index(op.f("ix_tasks_container_id"), "tasks", ["container_id"])
    op.create_index(op.f("ix_tasks_is_milestone"), "tasks", ["is_milestone"])
    op.create_index(op.f("ix_tasks_parent_id"), "tasks", ["parent_id"])

    op.create_table(
        "task_assignees",
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("person_id", sa.Uuid(), nullable=False),
        sa.PrimaryKeyConstraint("task_id", "person_id", name=op.f("pk_task_assignees")),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["tasks.id"],
            name=op.f("fk_task_assignees_task_id_tasks"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["person_id"],
            ["people.id"],
            name=op.f("fk_task_assignees_person_id_people"),
            ondelete="CASCADE",
        ),
    )
    op.create_index(op.f("ix_task_assignees_person_id"), "task_assignees", ["person_id"])

    op.create_table(
        "sync_runs",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("trigger", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="pending", nullable=False),
        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "stats",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sync_runs")),
        sa.CheckConstraint(
            "trigger IN ('scheduled', 'manual')", name=op.f("ck_sync_runs_trigger")
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'succeeded', 'partial', 'failed')",
            name=op.f("ck_sync_runs_status"),
        ),
    )
    # No máximo um run `pending` ou `running` por vez: todas as linhas ativas
    # têm a mesma chave (a constante true).
    op.create_index(
        "uq_sync_runs_single_active",
        "sync_runs",
        [sa.text("(true)")],
        unique=True,
        postgresql_where=sa.text("status IN ('pending', 'running')"),
    )

    op.create_table(
        "sync_state",
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("resource", sa.String(length=64), nullable=False),
        sa.Column("watermark", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_full_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("source", "resource", name=op.f("pk_sync_state")),
    )


def downgrade() -> None:
    # Índices e constraints caem junto com as tabelas. Não há tipos enum.
    op.drop_table("sync_state")
    op.drop_table("sync_runs")
    op.drop_table("task_assignees")
    op.drop_table("tasks")
    op.drop_table("people")
    op.drop_table("containers")
    op.drop_table("workspaces")
