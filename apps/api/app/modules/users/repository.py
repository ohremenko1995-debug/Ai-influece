"""User persistence."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import select

from app.modules.users.models import User, UserStatus

if TYPE_CHECKING:  # pragma: no cover - typing only
    from sqlalchemy.ext.asyncio import AsyncSession


def normalise_email(email: str) -> str:
    """Casefold and trim so lookups are stable regardless of how it was typed."""
    return email.strip().casefold()


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, user_id: uuid.UUID) -> User | None:
        return await self._session.get(User, user_id)

    async def get_by_email(self, email: str) -> User | None:
        result = await self._session.execute(
            select(User).where(User.email == normalise_email(email))
        )
        return result.scalar_one_or_none()

    async def create(
        self,
        *,
        email: str,
        display_name: str,
        status: UserStatus = UserStatus.INVITED,
        password_hash: str | None = None,
    ) -> User:
        user = User(
            email=normalise_email(email),
            display_name=display_name,
            status=status,
            password_hash=password_hash,
        )
        self._session.add(user)
        await self._session.flush()
        return user
