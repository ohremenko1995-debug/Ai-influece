"""Character Bible version persistence.

Append-only by construction: this repository exposes `create` and reads, plus one
narrowly scoped `demote_current` that touches nothing but the `is_current` flag.
There is no `update` and no `delete` — an identity change is a new row.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, select, update

from app.modules.character_versions.models import InfluencerVersion

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Sequence

    from sqlalchemy.ext.asyncio import AsyncSession


class InfluencerVersionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, version_id: uuid.UUID) -> InfluencerVersion | None:
        return await self._session.get(InfluencerVersion, version_id)

    async def get_current(self, influencer_id: uuid.UUID) -> InfluencerVersion | None:
        result = await self._session.execute(
            select(InfluencerVersion).where(
                InfluencerVersion.influencer_id == influencer_id,
                InfluencerVersion.is_current.is_(True),
            )
        )
        return result.scalar_one_or_none()

    async def get_by_number(
        self,
        *,
        influencer_id: uuid.UUID,
        version_number: int,
    ) -> InfluencerVersion | None:
        result = await self._session.execute(
            select(InfluencerVersion).where(
                InfluencerVersion.influencer_id == influencer_id,
                InfluencerVersion.version_number == version_number,
            )
        )
        return result.scalar_one_or_none()

    async def list_for_influencer(
        self,
        influencer_id: uuid.UUID,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> Sequence[InfluencerVersion]:
        result = await self._session.execute(
            select(InfluencerVersion)
            .where(InfluencerVersion.influencer_id == influencer_id)
            .order_by(InfluencerVersion.version_number.desc())
            .limit(limit)
            .offset(offset)
        )
        return result.scalars().all()

    async def count_for_influencer(self, influencer_id: uuid.UUID) -> int:
        result = await self._session.execute(
            select(func.count())
            .select_from(InfluencerVersion)
            .where(InfluencerVersion.influencer_id == influencer_id)
        )
        return int(result.scalar_one())

    async def next_version_number(self, influencer_id: uuid.UUID) -> int:
        """One past the highest existing number, starting at 1.

        Callers must already hold the influencer row lock — see
        `InfluencerRepository.get_for_update`.
        """
        result = await self._session.execute(
            select(func.max(InfluencerVersion.version_number)).where(
                InfluencerVersion.influencer_id == influencer_id
            )
        )
        highest: int | None = result.scalar_one()
        return (highest or 0) + 1

    async def demote_current(self, influencer_id: uuid.UUID) -> None:
        """Clear the `is_current` flag for this influencer.

        Must run *before* inserting the new current row: a partial unique index
        allows only one current version per influencer.
        """
        await self._session.execute(
            update(InfluencerVersion)
            .where(
                InfluencerVersion.influencer_id == influencer_id,
                InfluencerVersion.is_current.is_(True),
            )
            .values(is_current=False)
        )
        await self._session.flush()

    async def create(
        self,
        *,
        influencer_id: uuid.UUID,
        version_number: int,
        change_summary: str,
        created_by: uuid.UUID,
        biography: str | None,
        tone_of_voice: str | None,
        personality_traits: list[Any],
        prohibited_topics: list[Any],
        visual_constraints: dict[str, Any],
        speech_constraints: dict[str, Any],
    ) -> InfluencerVersion:
        version = InfluencerVersion(
            influencer_id=influencer_id,
            version_number=version_number,
            change_summary=change_summary,
            created_by=created_by,
            biography=biography,
            tone_of_voice=tone_of_voice,
            personality_traits=personality_traits,
            prohibited_topics=prohibited_topics,
            visual_constraints=visual_constraints,
            speech_constraints=speech_constraints,
            is_current=True,
        )
        self._session.add(version)
        await self._session.flush()
        return version
