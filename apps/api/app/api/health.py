"""Liveness and readiness probes.

`/health/live` answers as long as the process is up. `/health/ready` actually
touches Postgres, Redis and object storage, so a green readiness check means the
dependencies are reachable — not merely configured.

Unauthenticated on purpose: these are used by Docker, load balancers and CI, and
they expose no tenant data.
"""

from __future__ import annotations

import asyncio
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import text

from app import __version__
from app.api.deps import SettingsDep, get_db
from app.shared.db.session import Database
from app.shared.observability.logging import get_logger
from app.shared.queue.redis import check_redis
from app.shared.storage.s3 import build_object_storage

router = APIRouter(prefix="/health", tags=["health"])

_logger = get_logger(__name__)


class LivenessResponse(BaseModel):
    status: Literal["ok"] = "ok"
    version: str


class ReadinessResponse(BaseModel):
    status: Literal["ok", "degraded"]
    checks: dict[str, bool] = Field(description="One entry per dependency")


@router.get("/live", response_model=LivenessResponse, summary="Process liveness")
async def live() -> LivenessResponse:
    return LivenessResponse(version=__version__)


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    summary="Dependency readiness",
    responses={503: {"description": "At least one dependency is unreachable"}},
)
async def ready(
    response: Response,
    settings: SettingsDep,
    database: Annotated[Database, Depends(get_db)],
) -> ReadinessResponse:
    database_ok, redis_ok, storage_ok = await asyncio.gather(
        _check_database(database),
        check_redis(settings),
        build_object_storage(settings).check_bucket(),
    )
    checks = {"database": database_ok, "redis": redis_ok, "object_storage": storage_ok}
    healthy = all(checks.values())
    if not healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadinessResponse(status="ok" if healthy else "degraded", checks=checks)


async def _check_database(database: Database) -> bool:
    try:
        async with database.session() as session:
            await session.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001 - a probe must never raise
        _logger.warning("database_unreachable", error=str(exc))
        return False
    return True
