"""Configuração da aplicação, lida do ambiente (Fase 1).

O `.env` fica na raiz do repositório. O caminho é resolvido a partir deste
arquivo (backend/src/scarlet_scribe/config.py → raiz), e não do diretório
atual, então funciona rodando da raiz ou de `backend/` sem ler um `.env` de
fora do repositório. Variáveis do ambiente têm precedência sobre o `.env`.
Dentro do Docker o arquivo não existe e tudo vem do ambiente.
"""

from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

REPO_ROOT_ENV_FILE = Path(__file__).resolve().parents[3] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT_ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
        # Variável vazia (ex.: CLICKUP_API_TOKEN= copiado do exemplo) conta como ausente.
        env_ignore_empty=True,
    )

    # Banco
    database_url: str = Field(description="DSN do Postgres (postgresql+asyncpg://...)")

    # ClickUp (token pessoal do bot; vai em `Authorization: pk_...` sem `Bearer`).
    # Opcionais aqui para que a API e o Alembic subam sem eles; quem usa o
    # ClickUp (connector/worker) deve exigir que estejam preenchidos.
    clickup_api_token: SecretStr | None = None
    clickup_team_id: str | None = None
    clickup_space_ids: Annotated[list[str], NoDecode] = Field(default_factory=list)
    clickup_rate_limit_per_minute: int = 100

    # Sync
    sync_interval_minutes: int = 10
    sync_manual_cooldown_seconds: int = 60
    sync_full_reconcile_hours: int = 24

    @field_validator("clickup_space_ids", mode="before")
    @classmethod
    def _split_space_ids(cls, value: object) -> object:
        """Aceita lista separada por vírgula; vazio significa todos os spaces."""
        if value is None:
            return []
        if isinstance(value, str):
            return [part.strip() for part in value.split(",") if part.strip()]
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
