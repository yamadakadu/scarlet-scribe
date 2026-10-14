"""Vocabulário das execuções de sync, compartilhado por worker, API e banco."""

from enum import StrEnum


class SyncTrigger(StrEnum):
    SCHEDULED = "scheduled"
    MANUAL = "manual"


class SyncStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    FAILED = "failed"


# Estados em que um run ocupa a fila; no máximo um por vez (índice único parcial).
ACTIVE_SYNC_STATUSES: tuple[SyncStatus, ...] = (SyncStatus.PENDING, SyncStatus.RUNNING)
