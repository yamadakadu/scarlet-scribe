"""GitLab: issues

Mesmas convenções de `merge_requests` (0003). `state` é texto com CHECK;
`author_id` aceita nulo e `external_author_id` fica ao lado. O
`UNIQUE (repository_id, iid)` já cobre `repository_id`, então não há índice
só nessa coluna.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-21

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "issues",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("external_id", sa.Text(), nullable=False),
        sa.Column("repository_id", sa.Uuid(), nullable=False),
        sa.Column("iid", sa.Integer(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("confidential", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("issue_type", sa.Text(), nullable=True),
        sa.Column("web_url", sa.Text(), nullable=True),
        sa.Column("author_id", sa.Uuid(), nullable=True),
        sa.Column("external_author_id", sa.Text(), nullable=True),
        sa.Column("created_at_source", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_issues")),
        sa.UniqueConstraint("source", "external_id", name=op.f("uq_issues_source_external_id")),
        sa.UniqueConstraint("repository_id", "iid", name=op.f("uq_issues_repository_id_iid")),
        sa.CheckConstraint("state IN ('opened', 'closed')", name=op.f("ck_issues_state")),
        sa.ForeignKeyConstraint(
            ["repository_id"],
            ["repositories.id"],
            name=op.f("fk_issues_repository_id_repositories"),
        ),
        sa.ForeignKeyConstraint(
            ["author_id"],
            ["people.id"],
            name=op.f("fk_issues_author_id_people"),
            ondelete="SET NULL",
        ),
    )
    op.create_index(op.f("ix_issues_source_updated_at"), "issues", ["source_updated_at"])
    op.create_index(op.f("ix_issues_author_id"), "issues", ["author_id"])


def downgrade() -> None:
    op.drop_table("issues")
