"""Repositórios: ícone (avatar_url e repository_avatars) e repository_tags

`repository_tags` segue as convenções das sincronizadas, com `repository_id`
obrigatório e sem FK para `commits`. `repository_avatars` guarda os bytes do
ícone, um por repositório (apagado junto com ele).

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-15

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("repositories", sa.Column("avatar_url", sa.Text(), nullable=True))

    op.create_table(
        "repository_avatars",
        sa.Column("repository_id", sa.Uuid(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("content_type", sa.Text(), nullable=False),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("repository_id", name=op.f("pk_repository_avatars")),
        sa.ForeignKeyConstraint(
            ["repository_id"],
            ["repositories.id"],
            name=op.f("fk_repository_avatars_repository_id_repositories"),
            ondelete="CASCADE",
        ),
    )

    op.create_table(
        "repository_tags",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("external_id", sa.Text(), nullable=False),
        sa.Column("repository_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("commit_sha", sa.Text(), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_repository_tags")),
        sa.UniqueConstraint(
            "source", "external_id", name=op.f("uq_repository_tags_source_external_id")
        ),
        sa.UniqueConstraint("repository_id", "name", name=op.f("uq_repository_tags_repository_id_name")),
        sa.ForeignKeyConstraint(
            ["repository_id"],
            ["repositories.id"],
            name=op.f("fk_repository_tags_repository_id_repositories"),
        ),
    )
    op.create_index(
        op.f("ix_repository_tags_repository_id_commit_sha"),
        "repository_tags",
        ["repository_id", "commit_sha"],
    )


def downgrade() -> None:
    op.drop_table("repository_tags")
    op.drop_table("repository_avatars")
    op.drop_column("repositories", "avatar_url")
