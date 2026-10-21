"""Aplicação FastAPI: `uvicorn scarlet_scribe.api.app:app`.

Fase 1: todas as rotas são abertas, sem login.
"""

import logging
import socket

import asyncpg.exceptions
from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from sqlalchemy import exc as sa_exc

from scarlet_scribe.api.routes import (
    commits,
    health,
    issues,
    merge_requests,
    milestones,
    people,
    projects,
    repositories,
    sources,
    sync,
    tasks,
)
from scarlet_scribe.api.schemas import ErrorDetail

logger = logging.getLogger(__name__)

API_PREFIX = "/api/v1"

# Falhas de conexão que significam banco inacessível: conexão recusada ou
# derrubada, timeout de conexão e nome de host que não resolve. Só estas viram
# 503; erros de programação (tipo de parâmetro errado, uso concorrente da
# conexão, arquivo inexistente...) continuam 500, com traceback no log.
CONNECTION_FAILURES: tuple[type[BaseException], ...] = (
    ConnectionError,  # ConnectionRefusedError, ConnectionResetError, ...
    TimeoutError,
    socket.gaierror,
    # O asyncpg chega embrulhado num DBAPIError; estas classes só são olhadas
    # na causa original (`orig` ou cadeia `__cause__`).
    asyncpg.exceptions.PostgresConnectionError,  # inclui ConnectionDoesNotExistError
    asyncpg.exceptions.CannotConnectNowError,
)


def _is_connection_failure(exc: BaseException) -> bool:
    """Se o erro é de conexão com o banco, olhando a exceção e as suas causas."""
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, sa_exc.DBAPIError):
            if current.connection_invalidated:
                return True
            if isinstance(current.orig, CONNECTION_FAILURES):
                return True
        elif isinstance(current, CONNECTION_FAILURES):
            return True
        current = current.__cause__
    return False


def _database_unavailable_response(request: Request, exc: Exception) -> JSONResponse:
    """503 no formato padrão (`{detail}`), sem traceback para o cliente."""
    logger.warning(
        "banco indisponível em %s %s: %s", request.method, request.url.path, type(exc).__name__
    )
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"detail": "Banco de dados indisponível"},
    )


async def _on_connection_failure(request: Request, exc: Exception) -> JSONResponse:
    """Falha de conexão levantada direto (por exemplo, ao abrir a conexão)."""
    return _database_unavailable_response(request, exc)


async def _on_dbapi_error(request: Request, exc: Exception) -> JSONResponse:
    """503 só se o erro do driver for de conexão; senão, segue como sem handler.

    Relançar faz o erro chegar ao `ServerErrorMiddleware`: o cliente recebe o
    500 padrão e o traceback vai para o log.
    """
    if _is_connection_failure(exc):
        return _database_unavailable_response(request, exc)
    raise exc


def _operation_id(route: APIRoute) -> str:
    """operationId = nome da função, para nomes limpos no cliente TS gerado."""
    return route.name


def create_app() -> FastAPI:
    app = FastAPI(
        title="scarlet-scribe",
        version="0.1.0",
        description="API de leitura dos dados sincronizados (ClickUp e repositórios de código) (Fase 1, sem login).",
        openapi_url=f"{API_PREFIX}/openapi.json",
        docs_url=f"{API_PREFIX}/docs",
        redoc_url=None,
        generate_unique_id_function=_operation_id,
    )
    for exc_cls in (ConnectionError, TimeoutError, socket.gaierror):
        app.add_exception_handler(exc_cls, _on_connection_failure)
    app.add_exception_handler(sa_exc.DBAPIError, _on_dbapi_error)

    unavailable = {503: {"model": ErrorDetail, "description": "Banco de dados indisponível"}}
    for module in (
        health,
        projects,
        people,
        tasks,
        milestones,
        sync,
        sources,
        repositories,
        merge_requests,
        issues,
        commits,
    ):
        # O /health declara o próprio 503 (com HealthOut), que prevalece.
        app.include_router(module.router, prefix=API_PREFIX, responses=unavailable)
    return app


app = create_app()
