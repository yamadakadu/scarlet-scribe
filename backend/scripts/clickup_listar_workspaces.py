"""Lista os workspaces ("teams" na API v2) visíveis ao token do bot.

Uso (a partir da raiz do repositório):

    uv run --directory backend python scripts/clickup_listar_workspaces.py

Lê `CLICKUP_API_TOKEN` (e `CLICKUP_RATE_LIMIT_PER_MINUTE`) do ambiente ou do
`.env` da raiz, pelo `config.py`. Só faz GET. O token nunca é impresso.
"""

import asyncio
import sys

from scarlet_scribe.config import Settings
from scarlet_scribe.connectors.clickup.client import ClickUpClient, ClickUpError


class _ScriptSettings(Settings):
    # Este script não usa o banco: não exige DATABASE_URL.
    database_url: str | None = None


async def _main() -> int:
    settings = _ScriptSettings()
    if settings.clickup_api_token is None:
        print(
            "Erro: CLICKUP_API_TOKEN não está definido. Defina o token pessoal do bot "
            "(pk_...) no ambiente ou no .env da raiz do repositório.",
            file=sys.stderr,
        )
        return 2

    try:
        async with ClickUpClient.from_settings(settings) as client:
            user = await client.get_user()
            teams = await client.get_teams()
    except ClickUpError as exc:
        print(f"Erro ao consultar o ClickUp: {exc}", file=sys.stderr)
        return 1

    print(f"Token do usuário {user.username or '(sem nome)'} (id {user.id}).")
    if not teams:
        print("Nenhum workspace visível para este token.")
        return 0
    print(f"{len(teams)} workspace(s):")
    for team in teams:
        print(f"  {team.id}  {team.name}  ({len(team.members)} membros)")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
