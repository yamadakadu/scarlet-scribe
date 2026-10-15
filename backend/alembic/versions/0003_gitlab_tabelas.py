"""GitLab: repositories, merge_requests e commits

Mesmas convenções das tabelas sincronizadas da 0001. `state` é texto com
CHECK. `author_id` aceita nulo e `external_author_id` fica ao lado, como
`container_id` em `tasks`; as FKs `repository_id` são obrigatórias.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-15

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _synced_head() -> list[sa.Column]:
    return [
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("external_id", sa.Text(), nullable=False),
    ]


def _synced_tail() -> list[sa.Column]:
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
        "repositories",
        *_synced_head(),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("path_with_namespace", sa.Text(), nullable=False),
        sa.Column("web_url", sa.Text(), nullable=True),
        sa.Column("default_branch", sa.Text(), nullable=True),
        sa.Column("archived", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=True),
        *_synced_tail(),
        *_synced_keys("repositories"),
    )

    op.create_table(
        "merge_requests",
        *_synced_head(),
        sa.Column("repository_id", sa.Uuid(), nullable=False),
        sa.Column("iid", sa.Integer(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("draft", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("source_branch", sa.Text(), nullable=True),
        sa.Column("target_branch", sa.Text(), nullable=True),
        sa.Column("web_url", sa.Text(), nullable=True),
        sa.Column("author_id", sa.Uuid(), nullable=True),
        sa.Column("external_author_id", sa.Text(), nullable=True),
        sa.Column("created_at_source", sa.DateTime(timezone=True), nullable=True),
        sa.Column("merged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=True),
        *_synced_tail(),
        *_synced_keys("merge_requests"),
        sa.UniqueConstraint("repository_id", "iid", name=op.f("uq_merge_requests_repository_id_iid")),
        sa.CheckConstraint(
            "state IN ('opened', 'closed', 'merged', 'locked')",
            name=op.f("ck_merge_requests_state"),
        ),
        sa.ForeignKeyConstraint(
            ["repository_id"],
            ["repositories.id"],
            name=op.f("fk_merge_requests_repository_id_repositories"),
        ),
        sa.ForeignKeyConstraint(
            ["author_id"],
            ["people.id"],
            name=op.f("fk_merge_requests_author_id_people"),
            ondelete="SET NULL",
        ),
    )
    op.create_index(op.f("ix_merge_requests_repository_id"), "merge_requests", ["repository_id"])
    op.create_index(
        op.f("ix_merge_requests_source_updated_at"), "merge_requests", ["source_updated_at"]
    )
    op.create_index(op.f("ix_merge_requests_author_id"), "merge_requests", ["author_id"])

    op.create_table(
        "commits",
        *_synced_head(),
        sa.Column("repository_id", sa.Uuid(), nullable=False),
        sa.Column("sha", sa.Text(), nullable=False),
        sa.Column("short_sha", sa.Text(), nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("author_name", sa.Text(), nullable=True),
        sa.Column("author_email", sa.Text(), nullable=True),
        sa.Column("authored_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("committed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("web_url", sa.Text(), nullable=True),
        *_synced_tail(),
        *_synced_keys("commits"),
        sa.UniqueConstraint("repository_id", "sha", name=op.f("uq_commits_repository_id_sha")),
        sa.ForeignKeyConstraint(
            ["repository_id"],
            ["repositories.id"],
            name=op.f("fk_commits_repository_id_repositories"),
        ),
    )
    op.create_index(
        op.f("ix_commits_repository_id_authored_at"),
        "commits",
        ["repository_id", "authored_at"],
    )


def downgrade() -> None:
    op.drop_table("commits")
    op.drop_table("merge_requests")
    op.drop_table("repositories")
