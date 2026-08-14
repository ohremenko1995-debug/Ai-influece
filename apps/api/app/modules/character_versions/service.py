"""Character Bible versioning service."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from app.core.actor import CurrentActor
from app.core.errors import ConflictError, DomainValidationError, NotFoundError
from app.modules.audit.service import AuditService
from app.modules.character_versions.models import InfluencerVersion
from app.modules.character_versions.repository import InfluencerVersionRepository
from app.modules.character_versions.schemas import InfluencerVersionCreate
from app.modules.influencers.models import Influencer, InfluencerStatus
from app.modules.influencers.repository import InfluencerRepository
from app.shared.events.actions import DomainAction
from app.shared.permissions.permissions import Permission

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Sequence


class InfluencerVersionService:
    """Appends Character Bible revisions and reads their history.

    Version rows are not organization-scoped themselves — they hang off an
    influencer. Every entry point therefore loads the influencer through the
    organization-scoped repository first, so tenancy is checked before any version
    row is touched.
    """

    def __init__(
        self,
        *,
        influencers: InfluencerRepository,
        versions: InfluencerVersionRepository,
        audit: AuditService,
    ) -> None:
        self._influencers = influencers
        self._versions = versions
        self._audit = audit

    async def create_version(
        self,
        *,
        actor: CurrentActor,
        influencer_id: uuid.UUID,
        payload: InfluencerVersionCreate,
    ) -> InfluencerVersion:
        """Append version N+1 and make it current.

        Takes a row lock on the influencer so two concurrent writers cannot pick
        the same `version_number`. Order matters: the previous current row is
        demoted before the new one is inserted, because a partial unique index
        permits only one current version per influencer.
        """
        actor.require_permission(Permission.INFLUENCER_VERSION_CREATE)
        if actor.user_id is None:
            # `created_by` is a non-null FK to users; a system actor has no user
            # row to attribute the authorship of an identity revision to.
            raise DomainValidationError(
                "A Character Bible version must be created by a user",
                code="user_actor_required",
            )

        influencer = await self._influencers.get_for_update(
            organization_id=actor.organization_id,
            influencer_id=influencer_id,
        )
        if influencer is None:
            raise NotFoundError("Influencer not found", details={"id": str(influencer_id)})
        if influencer.status is InfluencerStatus.ARCHIVED:
            raise ConflictError(
                "Archived influencers are read-only",
                code="influencer_archived",
            )

        next_number = await self._versions.next_version_number(influencer_id)
        await self._versions.demote_current(influencer_id)

        version = await self._versions.create(
            influencer_id=influencer_id,
            version_number=next_number,
            change_summary=payload.change_summary,
            created_by=actor.user_id,
            biography=payload.biography,
            tone_of_voice=payload.tone_of_voice,
            personality_traits=list(payload.personality_traits),
            prohibited_topics=list(payload.prohibited_topics),
            visual_constraints=dict(payload.visual_constraints),
            speech_constraints=dict(payload.speech_constraints),
        )

        await self._audit.record_entity_change(
            actor=actor,
            action=DomainAction.INFLUENCER_VERSION_CREATED,
            entity=version,
        )
        # A second entry against the influencer itself, so the character's own
        # history tab shows that its identity moved to a new version.
        await self._audit.record(
            actor=actor,
            action=DomainAction.INFLUENCER_VERSION_PROMOTED,
            entity_type=Influencer.__name__,
            entity_id=influencer.id,
            after_data={
                "influencer_version_id": str(version.id),
                "version_number": version.version_number,
                "change_summary": version.change_summary,
            },
        )
        return version

    async def list_versions(
        self,
        *,
        actor: CurrentActor,
        influencer_id: uuid.UUID,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[Sequence[InfluencerVersion], int]:
        await self._require_influencer(actor, influencer_id)
        items = await self._versions.list_for_influencer(
            influencer_id,
            limit=limit,
            offset=offset,
        )
        total = await self._versions.count_for_influencer(influencer_id)
        return items, total

    async def get_current(
        self,
        *,
        actor: CurrentActor,
        influencer_id: uuid.UUID,
    ) -> InfluencerVersion:
        await self._require_influencer(actor, influencer_id)
        version = await self._versions.get_current(influencer_id)
        if version is None:
            raise NotFoundError(
                "This influencer has no Character Bible version yet",
                code="no_current_version",
            )
        return version

    async def get_version(
        self,
        *,
        actor: CurrentActor,
        influencer_id: uuid.UUID,
        version_number: int,
    ) -> InfluencerVersion:
        await self._require_influencer(actor, influencer_id)
        version = await self._versions.get_by_number(
            influencer_id=influencer_id,
            version_number=version_number,
        )
        if version is None:
            raise NotFoundError(
                f"Version {version_number} not found",
                details={"version_number": version_number},
            )
        return version

    async def _require_influencer(
        self,
        actor: CurrentActor,
        influencer_id: uuid.UUID,
    ) -> Influencer:
        actor.require_permission(Permission.INFLUENCER_READ)
        influencer = await self._influencers.get(
            organization_id=actor.organization_id,
            influencer_id=influencer_id,
        )
        if influencer is None:
            raise NotFoundError("Influencer not found", details={"id": str(influencer_id)})
        return influencer
