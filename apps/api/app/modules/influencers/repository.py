"""Influencer and disclosure-policy persistence.

Every query is filtered on `organization_id`. There is no unscoped read: a lookup
by primary key alone would be a cross-tenant leak.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ColumnElement, Select, func, select
from sqlalchemy.orm import noload

from app.modules.influencers.models import DisclosurePolicy, Influencer, InfluencerStatus

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Sequence

    from sqlalchemy.ext.asyncio import AsyncSession


class DisclosurePolicyRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(
        self,
        *,
        organization_id: uuid.UUID,
        policy_id: uuid.UUID,
    ) -> DisclosurePolicy | None:
        result = await self._session.execute(
            select(DisclosurePolicy).where(
                DisclosurePolicy.id == policy_id,
                DisclosurePolicy.organization_id == organization_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_by_code(
        self,
        *,
        organization_id: uuid.UUID,
        code: str,
    ) -> DisclosurePolicy | None:
        result = await self._session.execute(
            select(DisclosurePolicy).where(
                DisclosurePolicy.organization_id == organization_id,
                DisclosurePolicy.code == code,
            )
        )
        return result.scalar_one_or_none()

    async def list_all(self, organization_id: uuid.UUID) -> Sequence[DisclosurePolicy]:
        result = await self._session.execute(
            select(DisclosurePolicy)
            .where(DisclosurePolicy.organization_id == organization_id)
            .order_by(DisclosurePolicy.is_default.desc(), DisclosurePolicy.code)
        )
        return result.scalars().all()

    async def create(self, policy: DisclosurePolicy) -> DisclosurePolicy:
        self._session.add(policy)
        await self._session.flush()
        return policy

    async def clear_default(self, organization_id: uuid.UUID, *, keep: uuid.UUID) -> None:
        """Demote every other default so at most one policy is the default."""
        policies = await self.list_all(organization_id)
        for policy in policies:
            if policy.id != keep and policy.is_default:
                policy.is_default = False
        await self._session.flush()


class InfluencerRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def _scoped(self, organization_id: uuid.UUID) -> Select[tuple[Influencer]]:
        return select(Influencer).where(Influencer.organization_id == organization_id)

    async def get(
        self,
        *,
        organization_id: uuid.UUID,
        influencer_id: uuid.UUID,
    ) -> Influencer | None:
        result = await self._session.execute(
            self._scoped(organization_id).where(Influencer.id == influencer_id)
        )
        return result.unique().scalar_one_or_none()

    async def get_for_update(
        self,
        *,
        organization_id: uuid.UUID,
        influencer_id: uuid.UUID,
    ) -> Influencer | None:
        """Row-locked read.

        Used when appending a Character Bible version: the lock serialises
        concurrent version creation so two writers cannot pick the same
        `version_number`.
        """
        result = await self._session.execute(
            self._scoped(organization_id)
            .where(Influencer.id == influencer_id)
            # `disclosure_policy` is `lazy="joined"`, and PostgreSQL refuses
            # `FOR UPDATE` on the nullable side of an outer join. The lock only
            # needs the influencer row, so the relationship is not loaded at all.
            .options(noload(Influencer.disclosure_policy))
            .with_for_update()
        )
        return result.unique().scalar_one_or_none()

    async def get_by_code(
        self,
        *,
        organization_id: uuid.UUID,
        code: str,
    ) -> Influencer | None:
        result = await self._session.execute(
            self._scoped(organization_id).where(Influencer.code == code)
        )
        return result.unique().scalar_one_or_none()

    async def list_influencers(
        self,
        *,
        organization_id: uuid.UUID,
        statuses: Sequence[InfluencerStatus] | None = None,
        search: str | None = None,
        include_archived: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> Sequence[Influencer]:
        conditions = self._conditions(
            organization_id=organization_id,
            statuses=statuses,
            search=search,
            include_archived=include_archived,
        )
        result = await self._session.execute(
            select(Influencer)
            .where(*conditions)
            .order_by(Influencer.created_at.desc(), Influencer.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return result.unique().scalars().all()

    async def count_influencers(
        self,
        *,
        organization_id: uuid.UUID,
        statuses: Sequence[InfluencerStatus] | None = None,
        search: str | None = None,
        include_archived: bool = False,
    ) -> int:
        conditions = self._conditions(
            organization_id=organization_id,
            statuses=statuses,
            search=search,
            include_archived=include_archived,
        )
        result = await self._session.execute(
            select(func.count()).select_from(Influencer).where(*conditions)
        )
        return int(result.scalar_one())

    async def count_by_status(self, organization_id: uuid.UUID) -> dict[InfluencerStatus, int]:
        """Status histogram for the dashboard."""
        result = await self._session.execute(
            select(Influencer.status, func.count())
            .where(Influencer.organization_id == organization_id)
            .group_by(Influencer.status)
        )
        return dict(result.all())  # type: ignore[arg-type]

    async def create(self, influencer: Influencer) -> Influencer:
        self._session.add(influencer)
        await self._session.flush()
        return influencer

    @staticmethod
    def _conditions(
        *,
        organization_id: uuid.UUID,
        statuses: Sequence[InfluencerStatus] | None,
        search: str | None,
        include_archived: bool,
    ) -> list[ColumnElement[bool]]:
        """Filter predicates shared by the list and count queries.

        Returned as expressions rather than applied to a query, so a page and its
        total can never be computed from different filters.
        """
        conditions: list[ColumnElement[bool]] = [Influencer.organization_id == organization_id]
        if statuses:
            conditions.append(Influencer.status.in_(statuses))
        elif not include_archived:
            # Archived characters are hidden by default but never deleted.
            conditions.append(Influencer.status != InfluencerStatus.ARCHIVED)
        if search:
            pattern = f"%{search.strip()}%"
            conditions.append(
                Influencer.public_name.ilike(pattern) | Influencer.code.ilike(pattern)
            )
        return conditions
