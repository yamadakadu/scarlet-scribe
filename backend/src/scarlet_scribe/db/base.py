"""Base declarativa e convenções comuns às tabelas."""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import DateTime, Enum, MetaData, String, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column

# Nomes previsíveis para índices e constraints, para que as migrations
# (inclusive as geradas por autogenerate) sejam estáveis.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    type_annotation_map = {
        datetime: DateTime(timezone=True),
        dict[str, Any]: JSONB,
    }


def text_enum(enum_cls: type[StrEnum], name: str) -> Enum:
    """Enum guardado como texto com CHECK, não como tipo enum do Postgres.

    Acrescentar um valor depois é só trocar o CHECK numa migration, sem
    `ALTER TYPE`, e o downgrade não deixa tipos para trás.
    """
    return Enum(
        enum_cls,
        name=name,
        native_enum=False,
        create_constraint=True,
        length=32,
        values_callable=lambda members: [m.value for m in members],
        validate_strings=True,
    )


class SyncedMixin:
    """Colunas de toda tabela sincronizada a partir de uma ferramenta.

    - `id`: UUID interno; é o único id exposto pela API.
    - `source` + `external_id`: chave natural, única; alvo do upsert
      (`INSERT ... ON CONFLICT (source, external_id)`).
    - `raw`: payload original; só o mapper do conector interpreta.
    - `synced_at`: último sync que viu o registro.
    - `deleted_at`: soft delete quando o registro some na origem.
    """

    # sort_order: id e chave natural no início da tabela, metadados no fim.
    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=text("gen_random_uuid()"), sort_order=-3
    )
    source: Mapped[str] = mapped_column(String(32), sort_order=-2)
    external_id: Mapped[str] = mapped_column(Text, sort_order=-1)
    raw: Mapped[dict[str, Any]] = mapped_column(
        server_default=text("'{}'::jsonb"), sort_order=1
    )
    synced_at: Mapped[datetime] = mapped_column(server_default=func.now(), sort_order=2)
    deleted_at: Mapped[datetime | None] = mapped_column(sort_order=3)

    @declared_attr.directive
    @classmethod
    def __table_args__(cls) -> tuple[Any, ...]:
        return (UniqueConstraint("source", "external_id"),)
