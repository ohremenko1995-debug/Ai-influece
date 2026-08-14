"""Influencer Registry domain service.

Holds the two rules that must not be expressible from the client:

* the lifecycle transition table (`state_machine.py`), and
* the activation preconditions — a character cannot go live without an adult
  representation confirmation, a disclosure policy and a Character Bible.

Both are enforced here, so a hand-rolled HTTP call is refused exactly as a UI
click is.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy.exc import IntegrityError

from app.core.actor import CurrentActor
from app.core.errors import ConflictError, NotFoundError, PolicyViolationError
from app.modules.audit.serialization import snapshot
from app.modules.audit.service import AuditService
from app.modules.character_versions.repository import InfluencerVersionRepository
from app.modules.influencers.models import DisclosurePolicy, Influencer, InfluencerStatus
from app.modules.influencers.repository import DisclosurePolicyRepository, InfluencerRepository
from app.modules.influencers.schemas import (
    DisclosurePolicyCreate,
    DisclosurePolicyUpdate,
    InfluencerCreate,
    InfluencerUpdate,
)
from app.modules.influencers.state_machine import INFLUENCER_STATE_MACHINE
from app.shared.events.actions import DomainAction
from app.shared.permissions.permissions import Permission

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Sequence


class InfluencerService:
    """Create, read, update and re-state influencers."""

    def __init__(
        self,
        *,
        influencers: InfluencerRepository,
        policies: DisclosurePolicyRepository,
        versions: InfluencerVersionRepository,
        audit: AuditService,
    ) -> None:
        self._influencers = influencers
        self._policies = policies
        self._versions = versions
        self._audit = audit

    # --- Reads --------------------------------------------------------------

    async def get(self, *, actor: CurrentActor, influencer_id: uuid.UUID) -> Influencer:
        actor.require_permission(Permission.INFLUENCER_READ)
        influencer = await self._influencers.get(
            organization_id=actor.organization_id,
            influencer_id=influencer_id,
        )
        if influencer is None:
            raise NotFoundError("Influencer not found", details={"id": str(influencer_id)})
        return influencer

    async def list_influencers(
        self,
        *,
        actor: CurrentActor,
        statuses: Sequence[InfluencerStatus] | None = None,
        search: str | None = None,
        include_archived: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[Sequence[Influencer], int]:
        actor.require_permission(Permission.INFLUENCER_READ)
        items = await self._influencers.list_influencers(
            organization_id=actor.organization_id,
            statuses=statuses,
            search=search,
            include_archived=include_archived,
            limit=limit,
            offset=offset,
        )
        total = await self._influencers.count_influencers(
            organization_id=actor.organization_id,
            statuses=statuses,
            search=search,
            include_archived=include_archived,
        )
        return items, total

    async def activation_blockers(self, influencer: Influencer) -> list[str]:
        """Why this influencer cannot be activated. Empty means it can.

        Exposed on the detail response so the UI can explain the disabled button
        rather than simply hiding it.
        """
        blockers: list[str] = []
        if not influencer.adult_representation_confirmed:
            blockers.append("adult_representation_confirmed must be set")
        if influencer.disclosure_policy_id is None:
            blockers.append("a disclosure policy must be assigned")
        current = await self._versions.get_current(influencer.id)
        if current is None:
            blockers.append("a Character Bible version must exist")
        return blockers

    # --- Writes -------------------------------------------------------------

    async def create(self, *, actor: CurrentActor, payload: InfluencerCreate) -> Influencer:
        actor.require_permission(Permission.INFLUENCER_CREATE)

        policy: DisclosurePolicy | None = None
        if payload.disclosure_policy_id is not None:
            policy = await self._require_policy(actor, payload.disclosure_policy_id)

        existing = await self._influencers.get_by_code(
            organization_id=actor.organization_id,
            code=payload.code,
        )
        if existing is not None:
            raise ConflictError(
                f"Influencer code '{payload.code}' is already used in this organization",
                details={"code": payload.code},
            )

        influencer = Influencer(
            organization_id=actor.organization_id,
            code=payload.code,
            public_name=payload.public_name,
            status=InfluencerStatus.DRAFT,
            niche=payload.niche,
            primary_language=payload.primary_language,
            primary_market=payload.primary_market,
            adult_representation_confirmed=payload.adult_representation_confirmed,
            disclosure_policy_id=payload.disclosure_policy_id,
            # Assigned as an object, not just an id: otherwise the freshly created
            # instance has an unloaded `disclosure_policy`, and the response
            # serialiser would try to lazy-load it — synchronous IO in an async
            # request, which raises MissingGreenlet.
            disclosure_policy=policy,
        )
        try:
            await self._influencers.create(influencer)
        except IntegrityError as exc:  # concurrent create with the same code
            raise ConflictError(
                f"Influencer code '{payload.code}' is already used in this organization",
                details={"code": payload.code},
            ) from exc

        await self._audit.record_entity_change(
            actor=actor,
            action=DomainAction.INFLUENCER_CREATED,
            entity=influencer,
        )
        return influencer

    async def update(
        self,
        *,
        actor: CurrentActor,
        influencer_id: uuid.UUID,
        payload: InfluencerUpdate,
    ) -> Influencer:
        actor.require_permission(Permission.INFLUENCER_UPDATE)
        influencer = await self.get(actor=actor, influencer_id=influencer_id)
        if influencer.status is InfluencerStatus.ARCHIVED:
            raise ConflictError(
                "Archived influencers are read-only",
                code="influencer_archived",
            )

        changes = payload.model_dump(exclude_unset=True)
        if not changes:
            return influencer

        policy: DisclosurePolicy | None = None
        if changes.get("disclosure_policy_id") is not None:
            policy = await self._require_policy(actor, changes["disclosure_policy_id"])

        # Withdrawing the adult-representation confirmation from a live character
        # would leave it active without the compliance record that let it launch.
        if (
            changes.get("adult_representation_confirmed") is False
            and influencer.status is InfluencerStatus.ACTIVE
        ):
            raise PolicyViolationError(
                "Pause the influencer before withdrawing the adult representation confirmation",
                code="confirmation_required_while_active",
            )

        before = snapshot(influencer)
        for field, value in changes.items():
            setattr(influencer, field, value)
        if policy is not None:
            # Assigning the foreign key alone leaves the already-loaded
            # `disclosure_policy` relationship pointing at the previous value, so
            # the response would report a stale (or absent) policy. Setting the
            # relationship keeps the object graph and the FK in agreement.
            influencer.disclosure_policy = policy

        await self._audit.record_entity_change(
            actor=actor,
            action=DomainAction.INFLUENCER_UPDATED,
            entity=influencer,
            before=before,
        )
        return influencer

    async def change_status(
        self,
        *,
        actor: CurrentActor,
        influencer_id: uuid.UUID,
        target: InfluencerStatus,
        reason: str | None = None,
    ) -> Influencer:
        """Move an influencer through its lifecycle."""
        permission = (
            Permission.INFLUENCER_ARCHIVE
            if target is InfluencerStatus.ARCHIVED
            else Permission.INFLUENCER_UPDATE
        )
        actor.require_permission(permission)

        influencer = await self.get(actor=actor, influencer_id=influencer_id)
        INFLUENCER_STATE_MACHINE.assert_transition(influencer.status, target)

        if target is InfluencerStatus.ACTIVE:
            blockers = await self.activation_blockers(influencer)
            if blockers:
                raise PolicyViolationError(
                    "Influencer cannot be activated yet",
                    code="activation_blocked",
                    details={"blockers": blockers},
                )

        before = snapshot(influencer)
        influencer.status = target
        if target is InfluencerStatus.ARCHIVED:
            influencer.archived_at = datetime.now(UTC)

        action = (
            DomainAction.INFLUENCER_ARCHIVED
            if target is InfluencerStatus.ARCHIVED
            else DomainAction.INFLUENCER_STATUS_CHANGED
        )
        after = snapshot(influencer)
        if reason:
            after["transition_reason"] = reason
        await self._audit.record(
            actor=actor,
            action=action,
            entity_type=Influencer.__name__,
            entity_id=influencer.id,
            before_data=before,
            after_data=after,
        )
        return influencer

    # --- Disclosure policies ------------------------------------------------

    async def list_policies(self, *, actor: CurrentActor) -> Sequence[DisclosurePolicy]:
        actor.require_permission(Permission.POLICY_READ)
        return await self._policies.list_all(actor.organization_id)

    async def create_policy(
        self,
        *,
        actor: CurrentActor,
        payload: DisclosurePolicyCreate,
    ) -> DisclosurePolicy:
        actor.require_permission(Permission.POLICY_UPDATE)
        if (
            await self._policies.get_by_code(
                organization_id=actor.organization_id, code=payload.code
            )
            is not None
        ):
            raise ConflictError(
                f"Disclosure policy code '{payload.code}' already exists",
                details={"code": payload.code},
            )

        policy = DisclosurePolicy(
            organization_id=actor.organization_id,
            **payload.model_dump(),
        )
        await self._policies.create(policy)
        if policy.is_default:
            await self._policies.clear_default(actor.organization_id, keep=policy.id)

        await self._audit.record_entity_change(
            actor=actor,
            action=DomainAction.DISCLOSURE_POLICY_CREATED,
            entity=policy,
        )
        return policy

    async def update_policy(
        self,
        *,
        actor: CurrentActor,
        policy_id: uuid.UUID,
        payload: DisclosurePolicyUpdate,
    ) -> DisclosurePolicy:
        """Update a policy in place.

        Policies are mutable rather than versioned, so every field change is
        audited with before/after data. Content already approved keeps the
        disclosure text it was approved with — approval snapshots the text, so an
        edit here never rewrites history.
        """
        actor.require_permission(Permission.POLICY_UPDATE)
        policy = await self._require_policy(actor, policy_id)

        changes = payload.model_dump(exclude_unset=True)
        if not changes:
            return policy

        before = snapshot(policy)
        for field, value in changes.items():
            setattr(policy, field, value)
        if policy.is_default:
            await self._policies.clear_default(actor.organization_id, keep=policy.id)

        await self._audit.record_entity_change(
            actor=actor,
            action=DomainAction.DISCLOSURE_POLICY_UPDATED,
            entity=policy,
            before=before,
        )
        return policy

    async def _require_policy(
        self,
        actor: CurrentActor,
        policy_id: uuid.UUID,
    ) -> DisclosurePolicy:
        policy = await self._policies.get(
            organization_id=actor.organization_id,
            policy_id=policy_id,
        )
        if policy is None:
            raise NotFoundError(
                "Disclosure policy not found",
                details={"disclosure_policy_id": str(policy_id)},
            )
        return policy
