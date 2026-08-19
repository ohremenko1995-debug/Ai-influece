"""The ARQ worker's settings module must be able to start a worker.

`arq worker.main.WorkerSettings` is the command in `compose.yml` and in the worker
image. ARQ validates the settings while constructing the `Worker`, and it refuses
one with no functions and no cron jobs — a refusal that would otherwise surface only
when the container starts, in an environment nobody is watching.

The worker package is a separate deployment unit and is not installed into this
suite's environment, so its directory is placed on `sys.path` here.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from arq.worker import create_worker

from app.core.config import Settings
from app.shared.db.session import Database
from app.shared.observability.logging import configure_logging

_WORKER_ROOT = Path(__file__).resolve().parents[2] / "worker"
if str(_WORKER_ROOT) not in sys.path:
    sys.path.insert(0, str(_WORKER_ROOT))

from worker.main import WorkerSettings, heartbeat  # noqa: E402


# `create_worker` calls `asyncio.get_event_loop()`, which warns on 3.12 when no loop
# is running. ARQ's CLI does that too; these tests simply stay inside a loop so the
# suite's warnings-as-errors policy does not turn ARQ's deprecation into a failure.
async def test_worker_settings_can_construct_a_worker() -> None:
    worker = create_worker(WorkerSettings)
    assert worker.functions, "ARQ refuses to start a worker with nothing registered"


async def test_heartbeat_is_the_only_registered_job() -> None:
    """No generation task exists yet, and a placeholder one must not be added.

    When step 6 registers real tasks this assertion changes. Until then it is what
    stops a stub from being introduced quietly.
    """
    assert sorted(create_worker(WorkerSettings).functions) == ["cron:heartbeat"]


async def test_heartbeat_reaches_the_database(database: Database) -> None:
    """The heartbeat's whole purpose is to fail when the database is unreachable.

    It runs against the real engine — it reads nothing and writes nothing, so there
    is no state to isolate.
    """
    await heartbeat({"database": database})


def test_configure_logging_leaves_one_handler_chain_per_library(settings: Settings) -> None:
    """A library that both handles and propagates prints every line twice.

    ARQ's CLI installs a handler on the `arq` logger before the worker starts, which
    is how the worker's output came to be duplicated.
    """
    arq_logger = logging.getLogger("arq")
    arq_logger.addHandler(logging.StreamHandler())
    assert arq_logger.handlers

    configure_logging(settings)

    assert arq_logger.handlers == []
    assert arq_logger.propagate is True


def test_worker_settings_expose_the_operational_limits() -> None:
    """These are deliberate choices, not ARQ defaults; a silent change fails here."""
    assert WorkerSettings.max_jobs == 4
    assert WorkerSettings.job_timeout == 1800
    assert WorkerSettings.max_tries == 4
    assert WorkerSettings.health_check_interval == 30
