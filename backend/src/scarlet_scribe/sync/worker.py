"""Worker do sync: agendador (APScheduler) + consumo da fila `sync_runs`.

    uv run --directory backend scarlet-scribe-worker          # roda até SIGTERM/SIGINT
    uv run --directory backend scarlet-scribe-worker --once   # processa um run pendente e sai

- **Agendador:** a cada `SYNC_INTERVAL_MINUTES`, insere um run `scheduled`
  `pending` com `ON CONFLICT DO NOTHING` contra o índice único parcial de
  `sync_runs`. Se já houver um run `pending` ou `running`, nada é criado.
- **Fila:** a cada ~3 s, o worker tenta o advisory lock; com ele, pega o run
  `pending` mais antigo (`SELECT ... FOR UPDATE SKIP LOCKED`), marca como
  `running` com `started_at` e executa o `SyncService`.
- **Advisory lock (chave fixa):** dois workers nunca executam syncs ao mesmo
  tempo. É um lock **de sessão** (`pg_try_advisory_lock`), segurado numa
  conexão dedicada, separada das sessões que gravam os dados, do início ao fim
  do run. Por que não o lock de transação: ele exigiria uma transação aberta
  ("idle in transaction") durante o run inteiro nessa conexão, e um
  `idle_in_transaction_session_timeout` no servidor derrubaria o lock no meio
  do run. Por que a conexão dedicada: o lock de sessão pertence à conexão do
  Postgres, não à transação; numa conexão de pool compartilhada ele poderia
  voltar ao pool ainda preso, ou ser liberado por outro código. Aqui a conexão
  só serve ao lock: no fim, `pg_advisory_unlock` explícito; se o unlock falhar,
  a conexão é invalidada (fechada, não volta ao pool), o que também solta o
  lock. Se o processo morrer, o Postgres solta o lock ao perder a conexão.
- **Runs interrompidos:** com o lock na mão, nenhum outro worker está
  executando; então um run em `running` é sobra de um crash e vira `failed`
  com `error = "interrompido"`. Isso é feito ao iniciar e também a cada vez
  que o lock é obtido: assim, um worker vivo recupera o run de outro que
  morreu, e a fila não fica travada pelo índice único.
- **Encerramento:** SIGTERM ou SIGINT param o agendador e o loop. Um run em
  execução é cancelado e gravado como `failed` ("interrompido"); o conector é
  fechado e o lock, liberado.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import signal
import traceback
import uuid
from datetime import UTC

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession, async_sessionmaker

from scarlet_scribe.config import Settings, get_settings
from scarlet_scribe.db.models import SyncRunRow
from scarlet_scribe.db.session import get_engine, get_sessionmaker
from scarlet_scribe.domain.sync import SyncStatus
from scarlet_scribe.sync.service import INTERRUPTED_ERROR, ConnectorFactory, SyncService

logger = logging.getLogger("scarlet_scribe.sync.worker")

# Chave fixa do advisory lock do sync: os bytes ASCII de "scrbsync" como bigint.
SYNC_ADVISORY_LOCK_KEY = int.from_bytes(b"scrbsync", "big")
POLL_SECONDS = 3.0
SCHEDULER_JOB_ID = "sync-agendado"

# Um run agendado; o conflito com o índice único parcial (já há um run
# `pending` ou `running`) é ignorado.
_ENQUEUE_SCHEDULED = text(
    """
    INSERT INTO sync_runs (trigger, status)
    VALUES ('scheduled', 'pending')
    ON CONFLICT ((true)) WHERE status IN ('pending', 'running') DO NOTHING
    RETURNING id
    """
)


class Worker:
    """Agendador + fila. `connector_factory` vai para o `SyncService` (padrão: ClickUp)."""

    def __init__(
        self,
        settings: Settings,
        *,
        engine: AsyncEngine | None = None,
        sessionmaker: async_sessionmaker[AsyncSession] | None = None,
        connector_factory: ConnectorFactory | None = None,
        poll_seconds: float = POLL_SECONDS,
    ) -> None:
        self._settings = settings
        self._engine = engine or get_engine()
        self._sessionmaker = sessionmaker or get_sessionmaker()
        self._service = SyncService(
            settings, sessionmaker=self._sessionmaker, connector_factory=connector_factory
        )
        self._poll_seconds = poll_seconds
        self._lock_busy = False  # só para logar a mudança, não a cada tentativa

    # --- Agendador --------------------------------------------------------------

    async def enqueue_scheduled(self) -> uuid.UUID | None:
        """Cria um run `scheduled` `pending`, se não houver outro ativo."""
        try:
            async with self._sessionmaker() as session, session.begin():
                run_id = (await session.execute(_ENQUEUE_SCHEDULED)).scalar_one_or_none()
        except Exception as exc:
            _log_error("agendador: não foi possível criar o run", exc)
            return None
        if run_id is None:
            logger.info("agendador: já há um run pendente ou em execução; nenhum run criado")
        else:
            logger.info("agendador: run %s criado", run_id)
        return run_id

    # --- Fila -------------------------------------------------------------------

    async def process_next(self) -> bool:
        """Com o advisory lock: recupera runs interrompidos, pega o próximo
        `pending` e o executa. Devolve True se executou um run."""
        lock_conn = await self._engine.connect()
        locked = False
        try:
            locked = bool(
                (
                    await lock_conn.execute(
                        text("SELECT pg_try_advisory_lock(:key)"), {"key": SYNC_ADVISORY_LOCK_KEY}
                    )
                ).scalar()
            )
            # O lock é de sessão: sobrevive ao commit, e a conexão não fica
            # "idle in transaction" durante o run.
            await lock_conn.commit()
            if not locked:
                if not self._lock_busy:
                    logger.info("advisory lock ocupado por outro worker; aguardando")
                    self._lock_busy = True
                return False
            if self._lock_busy:
                logger.info("advisory lock obtido")
                self._lock_busy = False

            await self.recover_interrupted()
            run = await self._claim_next()
            if run is None:
                return False
            run_id, trigger = run
            logger.info("run %s (%s) iniciado", run_id, trigger)
            await self._service.execute(run_id)
            return True
        finally:
            await _release(lock_conn, locked)

    async def recover_interrupted(self) -> int:
        """Marca como `failed` ("interrompido") os runs que ficaram em `running`.

        Só pode ser chamado com o advisory lock: aí nenhum worker está executando.
        """
        async with self._sessionmaker() as session, session.begin():
            result = await session.execute(
                update(SyncRunRow)
                .where(SyncRunRow.status == SyncStatus.RUNNING)
                .values(status=SyncStatus.FAILED, error=INTERRUPTED_ERROR, finished_at=func.now())
                .returning(SyncRunRow.id)
            )
            ids = result.scalars().all()
        for run_id in ids:
            logger.warning("run %s estava em execução sem worker; marcado como interrompido", run_id)
        return len(ids)

    async def _claim_next(self) -> tuple[uuid.UUID, str] | None:
        async with self._sessionmaker() as session, session.begin():
            row = (
                await session.execute(
                    select(SyncRunRow.id, SyncRunRow.trigger)
                    .where(SyncRunRow.status == SyncStatus.PENDING)
                    .order_by(SyncRunRow.requested_at)
                    .limit(1)
                    .with_for_update(skip_locked=True)
                )
            ).first()
            if row is None:
                return None
            await session.execute(
                update(SyncRunRow)
                .where(SyncRunRow.id == row.id)
                .values(status=SyncStatus.RUNNING, started_at=func.now())
            )
        return row.id, str(row.trigger)

    # --- Loop -------------------------------------------------------------------

    async def run_forever(self) -> None:
        stop = asyncio.Event()
        _install_signal_handlers(stop)

        scheduler = AsyncIOScheduler(timezone=UTC)
        scheduler.add_job(
            self.enqueue_scheduled,
            "interval",
            minutes=self._settings.sync_interval_minutes,
            id=SCHEDULER_JOB_ID,
            coalesce=True,
            max_instances=1,
            misfire_grace_time=60,
        )
        scheduler.start()
        logger.info(
            "worker iniciado: sync agendado a cada %d min, fila consultada a cada %.0f s",
            self._settings.sync_interval_minutes, self._poll_seconds,
        )

        poll = asyncio.create_task(self._poll_loop(stop), name="sync-poll")
        stopped = asyncio.create_task(stop.wait(), name="sync-stop")
        try:
            await asyncio.wait({poll, stopped}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            logger.info("encerrando o worker")
            scheduler.shutdown(wait=False)
            for task in (poll, stopped):
                task.cancel()
            for task in (poll, stopped):
                with contextlib.suppress(asyncio.CancelledError):
                    await task
        logger.info("worker encerrado")

    async def run_once(self) -> bool:
        """Processa no máximo um run pendente (com a recuperação) e volta."""
        stop = asyncio.Event()
        _install_signal_handlers(stop)
        work = asyncio.create_task(self.process_next(), name="sync-once")
        stopped = asyncio.create_task(stop.wait(), name="sync-stop")
        try:
            await asyncio.wait({work, stopped}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for task in (work, stopped):
                task.cancel()
            for task in (work, stopped):
                with contextlib.suppress(asyncio.CancelledError):
                    await task
        ran = work.done() and not work.cancelled() and work.exception() is None and work.result()
        if not ran:
            logger.info("--once: nenhum run executado")
        return bool(ran)

    async def _poll_loop(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            ran = False
            try:
                ran = await self.process_next()
            except Exception as exc:
                _log_error("fila: erro ao processar", exc)
            if not ran:
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(stop.wait(), timeout=self._poll_seconds)


async def _release(lock_conn: AsyncConnection, locked: bool) -> None:
    """Solta o advisory lock e devolve a conexão; se algo falhar, invalida a
    conexão (fecha de verdade), o que também solta o lock no Postgres."""
    try:
        if locked:
            await lock_conn.execute(
                text("SELECT pg_advisory_unlock(:key)"), {"key": SYNC_ADVISORY_LOCK_KEY}
            )
            await lock_conn.commit()
        await lock_conn.close()
    except BaseException:
        with contextlib.suppress(Exception):
            await lock_conn.invalidate()
        with contextlib.suppress(Exception):
            await lock_conn.close()
        raise


def _install_signal_handlers(stop: asyncio.Event) -> None:
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _on_signal, sig, stop)


def _on_signal(sig: signal.Signals, stop: asyncio.Event) -> None:
    logger.info("sinal %s recebido", sig.name)
    stop.set()


def _log_error(prefix: str, exc: BaseException) -> None:
    """Tipo e pilha, sem a mensagem (pode conter parâmetros SQL com dados)."""
    stack = "".join(traceback.format_tb(exc.__traceback__)).rstrip()
    logger.error("%s: %s\n%s", prefix, type(exc).__name__, stack)


async def _amain(once: bool) -> int:
    settings = get_settings()
    engine = get_engine()
    try:
        worker = Worker(settings, engine=engine)
        if once:
            await worker.run_once()
        else:
            await worker.run_forever()
        return 0
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="scarlet-scribe-worker",
        description="Worker do sync: agendador e fila de sync_runs.",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="processa no máximo um run pendente (depois de recuperar os interrompidos) e sai, "
        "sem o agendador",
    )
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    raise SystemExit(asyncio.run(_amain(args.once)))


if __name__ == "__main__":
    main()
