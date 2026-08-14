"""Queue connection helpers.

`JobQueue` is a thin wrapper over the ARQ pool so that call sites depend on an
interface we own. Enqueue always carries an explicit job id: ARQ deduplicates on
job id, which is how the platform rule "every external side effect must have an
idempotency key" is realised at the queue layer.
"""

from __future__ import annotations

from typing import Any, Self

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings

from app.core.config import Settings
from app.shared.observability.logging import get_logger

_logger = get_logger(__name__)


def build_redis_settings(settings: Settings) -> RedisSettings:
    return RedisSettings(
        host=settings.redis_host,
        port=settings.redis_port,
        database=settings.redis_db,
    )


class JobQueue:
    """Owns the ARQ redis pool used to enqueue background work."""

    def __init__(self, pool: ArqRedis) -> None:
        self._pool = pool

    @classmethod
    async def connect(cls, settings: Settings) -> Self:
        pool = await create_pool(build_redis_settings(settings))
        return cls(pool)

    @property
    def pool(self) -> ArqRedis:
        return self._pool

    async def enqueue(
        self,
        task_name: str,
        *args: Any,
        job_id: str,
        **kwargs: Any,
    ) -> bool:
        """Enqueue `task_name` under `job_id`.

        Returns False when a job with that id is already queued or running, which
        makes a repeated enqueue a no-op rather than a duplicate side effect.
        """
        job = await self._pool.enqueue_job(task_name, *args, _job_id=job_id, **kwargs)
        if job is None:
            _logger.info("queue_enqueue_deduplicated", task=task_name, job_id=job_id)
            return False
        _logger.info("queue_enqueued", task=task_name, job_id=job_id)
        return True

    async def close(self) -> None:
        await self._pool.aclose()


async def check_redis(settings: Settings) -> bool:
    """Liveness probe for the queue backend."""
    try:
        pool = await create_pool(build_redis_settings(settings))
    except OSError as exc:  # connection refused / DNS failure
        _logger.warning("redis_unreachable", error=str(exc))
        return False
    try:
        await pool.ping()
    except Exception as exc:  # noqa: BLE001 - probe must never raise
        _logger.warning("redis_ping_failed", error=str(exc))
        return False
    else:
        return True
    finally:
        await pool.aclose()
