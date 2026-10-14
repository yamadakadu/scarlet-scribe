"""tasks.archived: tarefas arquivadas na origem

Coluna booleana, NOT NULL, com padrão `false`. As linhas já existentes ficam
com `false`; no Postgres 11+, `ADD COLUMN` com padrão constante não reescreve
a tabela.

Sem índice de propósito. A listagem padrão de `GET /tasks` filtra
`archived = false`, que pega quase todas as linhas: o planner prefere os
índices já existentes (`due_date`, `container_id`, ...) ou um seq scan, e um
índice em `archived` só custaria escrita. A listagem das arquivadas é rara e
pequena. Se o volume crescer, a opção é um índice parcial medido com EXPLAIN,
por exemplo `(due_date) WHERE NOT archived AND deleted_at IS NULL`.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-14

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tasks",
        sa.Column("archived", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("tasks", "archived")
