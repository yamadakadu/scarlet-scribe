"""Aplicação FastAPI: `uvicorn scarlet_scribe.api.app:app`.

Fase 1: todas as rotas são abertas, sem login.
"""

import logging

import asyncpg.exceptions
from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from sqlalchemy import exc as sa_exc

from scarlet_scribe.api.routes import health, milestones, people, projects, sync, tasks
from scarlet_scribe.api.schemas import ErrorDetail

logger = logging.getLogger(__name__)

API_PREFIX = "/api/v1"

# Erros que indicam banco inacessível (conexão recusada, caída ou expirada),
# vindos do SQLAlchemy ou direto do asyncpg. Viram 503 em qualquer rota.
DATABASE_UNAVAILABLE_ERRORS: tuple[type[Exception], ...] = (
    OSError,  # inclui ConnectionRefusedError e TimeoutError
    sa_exc.OperationalError,
    sa_exc.InterfaceError,
    asyncpg.exceptions.PostgresConnectionError,
    asyncpg.exceptions.CannotConnectNowError,
    asyncpg.exceptions.InterfaceError,
)


async def _database_unavailable(request: Request, exc: Exception) -> JSONResponse:
    """503 no formato padrão (`{detail}`), sem traceback para o cliente."""
    logger.warning(
        "banco indisponível em %s %s: %s", request.method, request.url.path, type(exc).__name__
    )
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"detail": "Banco de dados indisponível"},
    )


def _operation_id(route: APIRoute) -> str:
    """operationId = nome da função, para nomes limpos no cliente TS gerado."""
    return route.name


def create_app() -> FastAPI:
    app = FastAPI(
        title="scarlet-scribe",
        version="0.1.0",
        description="API de leitura dos dados sincronizados do ClickUp (Fase 1, sem login).",
        openapi_url=f"{API_PREFIX}/openapi.json",
        docs_url=f"{API_PREFIX}/docs",
        redoc_url=None,
        generate_unique_id_function=_operation_id,
    )
    for exc_cls in DATABASE_UNAVAILABLE_ERRORS:
        app.add_exception_handler(exc_cls, _database_unavailable)

    unavailable = {503: {"model": ErrorDetail, "description": "Banco de dados indisponível"}}
    for module in (health, projects, people, tasks, milestones, sync):
        # O /health declara o próprio 503 (com HealthOut), que prevalece.
        app.include_router(module.router, prefix=API_PREFIX, responses=unavailable)
    return app


app = create_app()
