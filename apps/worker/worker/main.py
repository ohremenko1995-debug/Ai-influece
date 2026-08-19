"""ARQ worker entrypoint: `arq worker.main.WorkerSettings`.

The worker is a second process type over the same modular monolith, not a separate
service. It installs the API package and imports the domain from it.

No generation tasks are registered: they arrive with MVP step 6. A placeholder task
would report success without doing work, which is exactly what the platform rules
forbid. The only registered job is a heartbeat, and it exists because ARQ refuses to
start a worker with nothing registered — see `heartbeat` for why that constraint is
worth satisfying honestly rather than with a no-op.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from arq.connections import RedisSettings
from arq.cron import CronJob, cron
from arq.typing import StartupShutdown, WorkerCoroutine
from arq.worker import Function
from sqlalchemy import text

from app.core.config import Settings, get_settings
from app.shared.db.session import Database, build_database
from app.shared.observability.logging import configure_logging, get_logger
from app.shared.queue import build_redis_settings

_logger = get_logger(__name__)

# Read once, at import: ARQ reads `WorkerSettings.__dict__` before it constructs
# anything, so `redis_settings` has to be a value rather than a callable. A bad
# configuration therefore fails at startup instead of on the first job.
_settings: Settings = get_settings()


async def startup(ctx: dict[Any, Any]) -> None:
    """Configure logging and open the database pool for the worker's lifetime."""
    configure_logging(_settings)
    database = build_database(_settings)
    ctx["settings"] = _settings
    ctx["database"] = database
    _logger.info("worker_started", environment=str(_settings.environment))


async def shutdown(ctx: dict[Any, Any]) -> None:
    """Dispose of the database pool so the process exits without dangling sockets."""
    database: Database | None = ctx.get("database")
    if database is not None:
        await database.dispose()
    _logger.info("worker_stopped")


async def heartbeat(ctx: dict[Any, Any]) -> None:
    """Prove that this worker can still reach the database.

    The worker container has no HTTP surface, so it has no readiness probe. Without
    this, a worker that has lost its database connection is indistinguishable from
    an idle one until the first real job fails.

    Success is deliberately quiet — one line a minute at INFO would bury everything
    else. Failure is loud: the exception propagates, ARQ logs the job as failed and
    retries it, so an outage produces a repeating error rather than silence.
    """
    database: Database = ctx["database"]
    async with database.session() as session:
        await session.execute(text("SELECT 1"))
    _logger.debug("worker_heartbeat")


class WorkerSettings:
    """ARQ configuration.

    Attribute names are ARQ's, not ours, and the annotations deliberately mirror
    `arq.typing.WorkerSettingsBase` so that a settings class ARQ would reject fails
    type-checking rather than container start-up.
    """

    functions: Sequence[WorkerCoroutine | Function] = ()
    cron_jobs: Sequence[CronJob] | None = [
        # Every minute, on one worker only (`unique`), and immediately at boot so a
        # misconfigured database is reported at startup rather than 60 seconds in.
        cron(heartbeat, second=0, run_at_startup=True, unique=True, max_tries=2),
    ]
    redis_settings: RedisSettings | None = build_redis_settings(_settings)
    on_startup: StartupShutdown | None = startup
    on_shutdown: StartupShutdown | None = shutdown

    # Generation jobs are long and GPU-bound, so concurrency stays low and the
    # timeout is generous. Both become meaningful with step 6; the values are here
    # because they are the reason this module exists.
    max_jobs: int = 4
    job_timeout: int = 1800

    # Results are read by the API to report job status, so they must outlive the
    # job by more than a poll interval.
    keep_result: int = 3600

    # A job that failed four times is not going to succeed on the fifth; it needs a
    # person. Retries themselves are safe because every enqueue carries an
    # idempotency key (app/shared/queue/redis.py).
    max_tries: int = 4

    # Frequent enough that a stalled worker shows up in `arq --check` and in the
    # container's own logs rather than an hour later.
    health_check_interval: int = 30
