"""Configuração da aplicação, lida do ambiente (Fase 1 e Fase M).

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

    # GitLab (token do bot com escopo `read_api`; vai em `PRIVATE-TOKEN`).
    # Tudo opcional: a API e o sync funcionam sem GitLab (ver `gitlab_enabled`).
    gitlab_url: str | None = None  # endereço da instância, sem /api/v4
    gitlab_api_token: SecretStr | None = None
    gitlab_group_ids: Annotated[list[str], NoDecode] = Field(default_factory=list)
    gitlab_project_ids: Annotated[list[str], NoDecode] = Field(default_factory=list)
    gitlab_ca_bundle: str | None = None
    # gitlab.com free aplica burst de 100 por usuário (spike FM-12); no self-hosted dá para aumentar pela variável.
    gitlab_rate_limit_per_minute: int = 100

    # Sync
    sync_interval_minutes: int = 10
    sync_manual_cooldown_seconds: int = 60
    sync_full_reconcile_hours: int = 24

    @field_validator(
        "clickup_space_ids", "gitlab_group_ids", "gitlab_project_ids", mode="before"
    )
    @classmethod
    def _split_ids(cls, value: object) -> object:
        """Aceita lista separada por vírgula; vazio significa lista vazia."""
        if value is None:
            return []
        if isinstance(value, str):
            return [part.strip() for part in value.split(",") if part.strip()]
        return value

    @field_validator("gitlab_url", mode="after")
    @classmethod
    def _strip_gitlab_url(cls, value: str | None) -> str | None:
        return value.rstrip("/") if value else value

    @property
    def gitlab_enabled(self) -> bool:
        """Verdadeiro com URL, token e ao menos um grupo ou projeto configurados."""
        return bool(
            self.gitlab_url
            and self.gitlab_api_token
            and (self.gitlab_group_ids or self.gitlab_project_ids)
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
