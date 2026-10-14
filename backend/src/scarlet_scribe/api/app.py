"""Aplicação FastAPI: `uvicorn scarlet_scribe.api.app:app`.

Fase 1: todas as rotas são abertas, sem login.
"""

from fastapi import FastAPI
from fastapi.routing import APIRoute

from scarlet_scribe.api.routes import health, milestones, people, projects, sync, tasks

API_PREFIX = "/api/v1"


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
    for module in (health, projects, people, tasks, milestones, sync):
        app.include_router(module.router, prefix=API_PREFIX)
    return app


app = create_app()
