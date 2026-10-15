"""`GET /sources`: os apps conectados, para a barra lateral."""

from fastapi import APIRouter
from sqlalchemy import func, select

from scarlet_scribe.api.deps import SessionDep, SettingsDep
from scarlet_scribe.api.schemas import SourceOut, SourcePage
from scarlet_scribe.db.models import RepositoryRow, TaskRow

router = APIRouter(tags=["sources"])


@router.get("/sources", response_model=SourcePage)
async def list_sources(session: SessionDep, settings: SettingsDep) -> SourcePage:
    """Uma entrada por app, sempre `clickup` e depois `gitlab`.

    `last_synced_at` vem do maior `synced_at` das linhas da fonte (`tasks` e
    `repositories`), sem depender de `sync_runs.stats`.
    """
    clickup_synced = await session.scalar(select(func.max(TaskRow.synced_at)))
    gitlab_synced = await session.scalar(select(func.max(RepositoryRow.synced_at)))
    items = [
        SourceOut(
            id="clickup",
            name="ClickUp",
            enabled=bool(settings.clickup_api_token and settings.clickup_team_id),
            last_synced_at=clickup_synced,
        ),
        SourceOut(
            id="gitlab",
            name="GitLab",
            enabled=settings.gitlab_enabled,
            last_synced_at=gitlab_synced,
        ),
    ]
    return SourcePage(items=items, total=len(items))
