"""`GET /health`: status da API, do banco e do último sync."""

import logging

from fastapi import APIRouter, Response, status
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError

from scarlet_scribe.api.deps import SessionDep
from scarlet_scribe.api.schemas import HealthOut, SyncRunOut
from scarlet_scribe.db.models import SyncRunRow

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


@router.get(
    "/health",
    response_model=HealthOut,
    responses={503: {"model": HealthOut, "description": "Banco indisponível"}},
)
async def get_health(session: SessionDep, response: Response) -> HealthOut:
    try:
        await session.execute(text("SELECT 1"))
        latest = await session.scalar(
            select(SyncRunRow).order_by(SyncRunRow.requested_at.desc()).limit(1)
        )
    except (SQLAlchemyError, OSError):
        logger.exception("health: banco indisponível")
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return HealthOut(status="error", database="error", latest_sync=None)
    return HealthOut(
        status="ok",
        database="ok",
        latest_sync=SyncRunOut.model_validate(latest) if latest is not None else None,
    )
