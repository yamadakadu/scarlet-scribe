"""`POST /sync`, `GET /sync/runs` e `GET /sync/runs/latest`.

A API só enfileira o run (linha `pending` em `sync_runs`); quem executa é o
worker. A API não fala com o ClickUp.
"""

import math

from fastapi import APIRouter, HTTPException, Response, status
from sqlalchemy import Select, func, select
from sqlalchemy.dialects.postgresql import insert

from scarlet_scribe.api.deps import PaginationDep, SessionDep, SettingsDep
from scarlet_scribe.api.queries import SYNC_RUNS_LATEST_FIRST, paginate
from scarlet_scribe.api.schemas import ErrorDetail, SyncRunOut, SyncRunPage
from scarlet_scribe.db.models import SyncRunRow
from scarlet_scribe.domain.sync import ACTIVE_SYNC_STATUSES, SyncTrigger

router = APIRouter(prefix="/sync", tags=["sync"])


def _active_run_stmt() -> Select[tuple[SyncRunRow]]:
    return (
        select(SyncRunRow)
        .where(SyncRunRow.status.in_(ACTIVE_SYNC_STATUSES))
        .order_by(*SYNC_RUNS_LATEST_FIRST)
        .limit(1)
    )


@router.post(
    "",
    response_model=SyncRunOut,
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        200: {"model": SyncRunOut, "description": "Já existe um run pendente ou em execução"},
        202: {"description": "Run manual criado (status pending)"},
        429: {
            "model": ErrorDetail,
            "description": "Cooldown do sync manual; o header Retry-After traz os segundos restantes",
            "headers": {"Retry-After": {"schema": {"type": "integer"}}},
        },
    },
)
async def request_sync(
    session: SessionDep, settings: SettingsDep, response: Response
) -> SyncRunOut:
    """Pede um sync manual, nesta ordem:

    1. se há um run `pending` ou `running`, devolve 200 com ele;
    2. se o último run manual foi pedido há menos de
       `SYNC_MANUAL_COOLDOWN_SECONDS`, devolve 429 com `Retry-After`;
    3. senão cria o run e devolve 202.

    Se dois pedidos simultâneos baterem no índice único parcial de
    `sync_runs`, o perdedor devolve 200 com o run do vencedor.
    """
    active = await session.scalar(_active_run_stmt())
    if active is not None:
        response.status_code = status.HTTP_200_OK
        return SyncRunOut.model_validate(active)

    # O relógio do banco é o mesmo que preenche `requested_at`.
    now, last_manual = (
        await session.execute(
            select(
                func.now(),
                select(func.max(SyncRunRow.requested_at))
                .where(SyncRunRow.trigger == SyncTrigger.MANUAL)
                .scalar_subquery(),
            )
        )
    ).one()
    cooldown = settings.sync_manual_cooldown_seconds
    if last_manual is not None:
        remaining = cooldown - (now - last_manual).total_seconds()
        if remaining > 0:
            retry_after = max(1, math.ceil(remaining))
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Aguarde {retry_after} s para pedir outro sync manual",
                headers={"Retry-After": str(retry_after)},
            )

    created = await session.scalar(
        insert(SyncRunRow)
        .values(trigger=SyncTrigger.MANUAL)
        .on_conflict_do_nothing()
        .returning(SyncRunRow)
    )
    await session.commit()
    if created is not None:
        return SyncRunOut.model_validate(created)

    # Corrida: outro pedido criou o run ativo entre a verificação e a inserção.
    response.status_code = status.HTTP_200_OK
    existing = await session.scalar(_active_run_stmt())
    if existing is None:  # o run já terminou; devolve o mais recente
        existing = await session.scalar(
            select(SyncRunRow).order_by(*SYNC_RUNS_LATEST_FIRST).limit(1)
        )
    return SyncRunOut.model_validate(existing)


@router.get("/runs", response_model=SyncRunPage)
async def list_sync_runs(session: SessionDep, page: PaginationDep) -> SyncRunPage:
    """Histórico dos runs, do mais recente para o mais antigo."""
    stmt = select(SyncRunRow).order_by(*SYNC_RUNS_LATEST_FIRST)
    rows, total = await paginate(session, stmt, page)
    return SyncRunPage(items=[SyncRunOut.model_validate(r) for r in rows], total=total)


@router.get("/runs/latest", response_model=SyncRunOut | None)
async def get_latest_sync_run(session: SessionDep) -> SyncRunOut | None:
    """O run mais recente, ou `null` se nunca houve sync."""
    latest = await session.scalar(select(SyncRunRow).order_by(*SYNC_RUNS_LATEST_FIRST).limit(1))
    return SyncRunOut.model_validate(latest) if latest is not None else None
