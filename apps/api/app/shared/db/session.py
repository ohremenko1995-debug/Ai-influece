"""Engine and session lifecycle.

One `Database` instance owns one connection pool. The API creates it during
lifespan startup and stores it on `app.state`; the worker creates its own. Tests
build a third against the test database. There is no module-level engine, so no
implicit shared pool between processes or test cases.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import lru_cache

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import Settings, get_settings


class Database:
    """Owns an async engine and its session factory."""

    def __init__(
        self,
        url: str,
        *,
        echo: bool = False,
        pool_size: int = 10,
        max_overflow: int = 5,
    ) -> None:
        self._engine: AsyncEngine = create_async_engine(
            url,
            echo=echo,
            pool_size=pool_size,
            max_overflow=max_overflow,
            pool_pre_ping=True,
            # Server-side statement caching interacts badly with pgbouncer in
            # transaction mode; keep it small and predictable.
            connect_args={"statement_cache_size": 0},
        )
        self._session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
            bind=self._engine,
            expire_on_commit=False,
            autoflush=False,
        )

    @property
    def engine(self) -> AsyncEngine:
        return self._engine

    @property
    def session_factory(self) -> async_sessionmaker[AsyncSession]:
        return self._session_factory

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        """Unit of work: commit on clean exit, roll back on any exception.

        Domain services never commit. That is what keeps an entity change and its
        audit-log row in the same transaction — either both land or neither does.
        """
        async with self._session_factory() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise
            else:
                await session.commit()

    async def dispose(self) -> None:
        await self._engine.dispose()


def build_database(settings: Settings) -> Database:
    """Construct the application `Database`.

    Importing the model registry here — rather than expecting each entrypoint to
    remember — is what guarantees the ORM mappers are complete. A process that
    imported only some model modules would fail to resolve string-based
    relationships (`Influencer.versions` -> `InfluencerVersion`) at first use.
    The import is local because models import from this package's `base` module,
    so a module-level import would be circular.
    """
    import app.shared.db.registry  # noqa: F401, PLC0415 - completes the mapper registry

    return Database(
        settings.database_url,
        echo=settings.db_echo,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
    )


@lru_cache(maxsize=1)
def get_database() -> Database:
    """Cached `Database` for processes without a FastAPI lifespan (the worker, CLI)."""
    return build_database(get_settings())
