"""Organization and membership persistence."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app.modules.organizations.models import Membership, Organization
from app.shared.permissions.roles import Role

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Sequence

    from sqlalchemy.ext.asyncio import AsyncSession


class OrganizationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, organization_id: uuid.UUID) -> Organization | None:
        return await self._session.get(Organization, organization_id)

    async def get_by_slug(self, slug: str) -> Organization | None:
        result = await self._session.execute(select(Organization).where(Organization.slug == slug))
        return result.scalar_one_or_none()

    async def create(self, *, name: str, slug: str) -> Organization:
        organization = Organization(name=name, slug=slug)
        self._session.add(organization)
        await self._session.flush()
        return organization


class MembershipRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_active(
        self,
        *,
        user_id: uuid.UUID,
        organization_id: uuid.UUID,
    ) -> Membership | None:
        """The caller's live membership in one organization, or None."""
        result = await self._session.execute(
            select(Membership)
            .where(
                Membership.user_id == user_id,
                Membership.organization_id == organization_id,
                Membership.revoked_at.is_(None),
            )
            .options(joinedload(Membership.organization))
        )
        return result.unique().scalar_one_or_none()

    async def list_active_for_user(self, user_id: uuid.UUID) -> Sequence[Membership]:
        """Every live membership, oldest first — the first is the default org."""
        result = await self._session.execute(
            select(Membership)
            .where(Membership.user_id == user_id, Membership.revoked_at.is_(None))
            .options(joinedload(Membership.organization))
            .order_by(Membership.created_at, Membership.id)
        )
        return result.unique().scalars().all()

    async def list_for_organization(self, organization_id: uuid.UUID) -> Sequence[Membership]:
        result = await self._session.execute(
            select(Membership)
            .where(Membership.organization_id == organization_id, Membership.revoked_at.is_(None))
            .options(joinedload(Membership.user), joinedload(Membership.organization))
            .order_by(Membership.created_at)
        )
        return result.unique().scalars().all()

    async def create(
        self,
        *,
        organization_id: uuid.UUID,
        user_id: uuid.UUID,
        role: Role,
    ) -> Membership:
        membership = Membership(
            organization_id=organization_id,
            user_id=user_id,
            role=role,
        )
        self._session.add(membership)
        await self._session.flush()
        return membership
