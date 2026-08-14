"""Influencer Registry service tests (real database)."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest

from app.core.errors import (
    ConflictError,
    InvalidTransitionError,
    NotFoundError,
    PermissionDeniedError,
    PolicyViolationError,
)
from app.modules.character_versions.schemas import InfluencerVersionCreate
from app.modules.influencers.models import InfluencerStatus
from app.modules.influencers.schemas import InfluencerCreate, InfluencerUpdate
from app.shared.permissions.roles import Role

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.modules.character_versions.service import InfluencerVersionService
    from app.modules.influencers.service import InfluencerService
    from tests.conftest import Tenant

pytestmark = pytest.mark.integration


def _payload(code: str = "nora", **overrides: object) -> InfluencerCreate:
    data: dict[str, object] = {
        "code": code,
        "public_name": "Nora",
        "primary_language": "en",
        "primary_market": "DE",
        "niche": "fitness",
    }
    data.update(overrides)
    return InfluencerCreate(**data)  # type: ignore[arg-type]


def _bible(summary: str = "Initial identity") -> InfluencerVersionCreate:
    return InfluencerVersionCreate(
        change_summary=summary,
        biography="Nora is a virtual fitness coach.",
        tone_of_voice="Direct, warm, never pushy.",
        personality_traits=["disciplined", "encouraging"],
        prohibited_topics=["medical advice", "politics"],
        visual_constraints={"eye_color": "green", "no_tattoos": True},
        speech_constraints={"max_wpm": 165},
    )


# --- Creation ----------------------------------------------------------------


async def test_influencer_is_created_in_draft(
    influencer_service: InfluencerService,
    tenant: Tenant,
) -> None:
    influencer = await influencer_service.create(
        actor=tenant.actor(Role.OWNER),
        payload=_payload(),
    )
    assert influencer.status is InfluencerStatus.DRAFT
    assert influencer.organization_id == tenant.organization.id
    assert influencer.archived_at is None


async def test_adult_representation_defaults_to_false(
    influencer_service: InfluencerService,
    tenant: Tenant,
) -> None:
    """A compliance confirmation must be given, never assumed."""
    influencer = await influencer_service.create(
        actor=tenant.actor(Role.OWNER),
        payload=_payload(),
    )
    assert influencer.adult_representation_confirmed is False


async def test_duplicate_code_within_an_organization_conflicts(
    influencer_service: InfluencerService,
    tenant: Tenant,
) -> None:
    actor = tenant.actor(Role.OWNER)
    await influencer_service.create(actor=actor, payload=_payload("nora"))
    with pytest.raises(ConflictError) as exc_info:
        await influencer_service.create(actor=actor, payload=_payload("nora"))
    assert exc_info.value.details["code"] == "nora"


async def test_same_code_is_allowed_in_another_organization(
    influencer_service: InfluencerService,
    tenant: Tenant,
    other_tenant: Tenant,
) -> None:
    """Codes are unique per tenant, not globally."""
    await influencer_service.create(actor=tenant.actor(Role.OWNER), payload=_payload("nora"))
    second = await influencer_service.create(
        actor=other_tenant.actor(Role.OWNER),
        payload=_payload("nora"),
    )
    assert second.organization_id == other_tenant.organization.id


async def test_unknown_disclosure_policy_is_rejected(
    influencer_service: InfluencerService,
    tenant: Tenant,
) -> None:
    with pytest.raises(NotFoundError):
        await influencer_service.create(
            actor=tenant.actor(Role.OWNER),
            payload=_payload(disclosure_policy_id=uuid.uuid4()),
        )


async def test_policy_from_another_organization_is_not_found(
    influencer_service: InfluencerService,
    tenant: Tenant,
    other_tenant: Tenant,
) -> None:
    """Referencing another tenant's policy must not be possible."""
    with pytest.raises(NotFoundError):
        await influencer_service.create(
            actor=tenant.actor(Role.OWNER),
            payload=_payload(disclosure_policy_id=other_tenant.policy.id),
        )


@pytest.mark.parametrize("role", [Role.OPERATOR, Role.REVIEWER, Role.ANALYST, Role.AGENT])
async def test_roles_without_create_permission_are_refused(
    influencer_service: InfluencerService,
    tenant: Tenant,
    role: Role,
) -> None:
    with pytest.raises(PermissionDeniedError):
        await influencer_service.create(actor=tenant.actor(role), payload=_payload())


# --- Reads and isolation -----------------------------------------------------


async def test_reading_another_organizations_influencer_is_a_404(
    influencer_service: InfluencerService,
    tenant: Tenant,
    other_tenant: Tenant,
) -> None:
    """404 rather than 403: the API must not confirm the row exists."""
    influencer = await influencer_service.create(
        actor=tenant.actor(Role.OWNER),
        payload=_payload(),
    )
    with pytest.raises(NotFoundError):
        await influencer_service.get(
            actor=other_tenant.actor(Role.OWNER),
            influencer_id=influencer.id,
        )


async def test_list_excludes_archived_by_default(
    influencer_service: InfluencerService,
    tenant: Tenant,
) -> None:
    actor = tenant.actor(Role.OWNER)
    keep = await influencer_service.create(actor=actor, payload=_payload("keeper"))
    gone = await influencer_service.create(actor=actor, payload=_payload("retired"))
    await influencer_service.change_status(
        actor=actor,
        influencer_id=gone.id,
        target=InfluencerStatus.ARCHIVED,
    )

    items, total = await influencer_service.list_influencers(actor=actor)
    assert {item.id for item in items} == {keep.id}
    assert total == 1

    items, total = await influencer_service.list_influencers(actor=actor, include_archived=True)
    assert {item.id for item in items} == {keep.id, gone.id}
    assert total == 2


async def test_list_does_not_leak_across_organizations(
    influencer_service: InfluencerService,
    tenant: Tenant,
    other_tenant: Tenant,
) -> None:
    await influencer_service.create(actor=tenant.actor(Role.OWNER), payload=_payload("ours"))
    await influencer_service.create(
        actor=other_tenant.actor(Role.OWNER),
        payload=_payload("theirs"),
    )
    items, total = await influencer_service.list_influencers(actor=tenant.actor(Role.ANALYST))
    assert [item.code for item in items] == ["ours"]
    assert total == 1


# --- Activation gate ---------------------------------------------------------


async def test_activation_lists_every_blocker(
    influencer_service: InfluencerService,
    tenant: Tenant,
) -> None:
    influencer = await influencer_service.create(
        actor=tenant.actor(Role.OWNER),
        payload=_payload(),
    )
    blockers = await influencer_service.activation_blockers(influencer)
    assert len(blockers) == 3
    assert any("adult_representation_confirmed" in blocker for blocker in blockers)
    assert any("disclosure policy" in blocker for blocker in blockers)
    assert any("Character Bible" in blocker for blocker in blockers)


async def test_activation_is_refused_while_blockers_remain(
    influencer_service: InfluencerService,
    tenant: Tenant,
) -> None:
    actor = tenant.actor(Role.OWNER)
    influencer = await influencer_service.create(actor=actor, payload=_payload())
    with pytest.raises(PolicyViolationError) as exc_info:
        await influencer_service.change_status(
            actor=actor,
            influencer_id=influencer.id,
            target=InfluencerStatus.ACTIVE,
        )
    assert exc_info.value.code == "activation_blocked"
    assert exc_info.value.details["blockers"]


async def test_activation_succeeds_once_every_precondition_is_met(
    influencer_service: InfluencerService,
    version_service: InfluencerVersionService,
    tenant: Tenant,
) -> None:
    actor = tenant.actor(Role.OWNER)
    influencer = await influencer_service.create(
        actor=actor,
        payload=_payload(
            adult_representation_confirmed=True,
            disclosure_policy_id=tenant.policy.id,
        ),
    )
    await version_service.create_version(
        actor=actor,
        influencer_id=influencer.id,
        payload=_bible(),
    )

    activated = await influencer_service.change_status(
        actor=actor,
        influencer_id=influencer.id,
        target=InfluencerStatus.ACTIVE,
    )
    assert activated.status is InfluencerStatus.ACTIVE
    assert await influencer_service.activation_blockers(activated) == []


async def test_missing_only_the_character_bible_still_blocks_activation(
    influencer_service: InfluencerService,
    tenant: Tenant,
) -> None:
    actor = tenant.actor(Role.OWNER)
    influencer = await influencer_service.create(
        actor=actor,
        payload=_payload(
            adult_representation_confirmed=True,
            disclosure_policy_id=tenant.policy.id,
        ),
    )
    blockers = await influencer_service.activation_blockers(influencer)
    assert blockers == ["a Character Bible version must exist"]


# --- Lifecycle ---------------------------------------------------------------


async def _activate(
    influencer_service: InfluencerService,
    version_service: InfluencerVersionService,
    tenant: Tenant,
    code: str = "nora",
) -> uuid.UUID:
    actor = tenant.actor(Role.OWNER)
    influencer = await influencer_service.create(
        actor=actor,
        payload=_payload(
            code,
            adult_representation_confirmed=True,
            disclosure_policy_id=tenant.policy.id,
        ),
    )
    await version_service.create_version(
        actor=actor,
        influencer_id=influencer.id,
        payload=_bible(),
    )
    await influencer_service.change_status(
        actor=actor,
        influencer_id=influencer.id,
        target=InfluencerStatus.ACTIVE,
    )
    return influencer.id


async def test_pause_and_resume(
    influencer_service: InfluencerService,
    version_service: InfluencerVersionService,
    tenant: Tenant,
) -> None:
    actor = tenant.actor(Role.OWNER)
    influencer_id = await _activate(influencer_service, version_service, tenant)

    paused = await influencer_service.change_status(
        actor=actor,
        influencer_id=influencer_id,
        target=InfluencerStatus.PAUSED,
    )
    assert paused.status is InfluencerStatus.PAUSED

    resumed = await influencer_service.change_status(
        actor=actor,
        influencer_id=influencer_id,
        target=InfluencerStatus.ACTIVE,
    )
    assert resumed.status is InfluencerStatus.ACTIVE


async def test_archiving_stamps_archived_at_and_is_terminal(
    influencer_service: InfluencerService,
    tenant: Tenant,
) -> None:
    actor = tenant.actor(Role.OWNER)
    influencer = await influencer_service.create(actor=actor, payload=_payload())

    archived = await influencer_service.change_status(
        actor=actor,
        influencer_id=influencer.id,
        target=InfluencerStatus.ARCHIVED,
    )
    assert archived.status is InfluencerStatus.ARCHIVED
    assert archived.archived_at is not None
    assert archived.is_archived

    with pytest.raises(InvalidTransitionError):
        await influencer_service.change_status(
            actor=actor,
            influencer_id=influencer.id,
            target=InfluencerStatus.ACTIVE,
        )


async def test_archived_influencers_are_read_only(
    influencer_service: InfluencerService,
    tenant: Tenant,
) -> None:
    actor = tenant.actor(Role.OWNER)
    influencer = await influencer_service.create(actor=actor, payload=_payload())
    await influencer_service.change_status(
        actor=actor,
        influencer_id=influencer.id,
        target=InfluencerStatus.ARCHIVED,
    )
    with pytest.raises(ConflictError) as exc_info:
        await influencer_service.update(
            actor=actor,
            influencer_id=influencer.id,
            payload=InfluencerUpdate(public_name="Renamed"),
        )
    assert exc_info.value.code == "influencer_archived"


async def test_archiving_requires_the_archive_permission(
    influencer_service: InfluencerService,
    tenant: Tenant,
) -> None:
    """Operators may edit an influencer but not retire one."""
    influencer = await influencer_service.create(
        actor=tenant.actor(Role.OWNER),
        payload=_payload(),
    )
    with pytest.raises(PermissionDeniedError):
        await influencer_service.change_status(
            actor=tenant.actor(Role.OPERATOR),
            influencer_id=influencer.id,
            target=InfluencerStatus.ARCHIVED,
        )


# --- Updates -----------------------------------------------------------------


async def test_update_applies_only_the_supplied_fields(
    influencer_service: InfluencerService,
    tenant: Tenant,
) -> None:
    actor = tenant.actor(Role.OWNER)
    influencer = await influencer_service.create(actor=actor, payload=_payload())
    updated = await influencer_service.update(
        actor=actor,
        influencer_id=influencer.id,
        payload=InfluencerUpdate(public_name="Nora Prime"),
    )
    assert updated.public_name == "Nora Prime"
    assert updated.niche == "fitness"
    assert updated.primary_market == "DE"


async def test_confirmation_cannot_be_withdrawn_while_active(
    influencer_service: InfluencerService,
    version_service: InfluencerVersionService,
    tenant: Tenant,
) -> None:
    """A live character must not lose the record that allowed it to launch."""
    actor = tenant.actor(Role.OWNER)
    influencer_id = await _activate(influencer_service, version_service, tenant)

    with pytest.raises(PolicyViolationError) as exc_info:
        await influencer_service.update(
            actor=actor,
            influencer_id=influencer_id,
            payload=InfluencerUpdate(adult_representation_confirmed=False),
        )
    assert exc_info.value.code == "confirmation_required_while_active"


async def test_confirmation_can_be_withdrawn_once_paused(
    influencer_service: InfluencerService,
    version_service: InfluencerVersionService,
    tenant: Tenant,
) -> None:
    actor = tenant.actor(Role.OWNER)
    influencer_id = await _activate(influencer_service, version_service, tenant)
    await influencer_service.change_status(
        actor=actor,
        influencer_id=influencer_id,
        target=InfluencerStatus.PAUSED,
    )
    updated = await influencer_service.update(
        actor=actor,
        influencer_id=influencer_id,
        payload=InfluencerUpdate(adult_representation_confirmed=False),
    )
    assert updated.adult_representation_confirmed is False
