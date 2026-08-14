"""Audit log tests.

Every critical state change must leave an entry, the entry must carry enough
before/after data to explain the change, and it must never carry a credential.
"""

from __future__ import annotations

import inspect
import json
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import inspect as sa_inspect

from app.core.actor import CurrentActor
from app.core.errors import PermissionDeniedError
from app.modules.audit.models import AuditLog
from app.modules.audit.repository import AuditRepository
from app.modules.audit.serialization import REDACTED, diff, snapshot
from app.modules.audit.service import AuditService
from app.modules.character_versions.schemas import InfluencerVersionCreate
from app.modules.influencers.models import Influencer, InfluencerStatus
from app.modules.influencers.schemas import (
    DisclosurePolicyUpdate,
    InfluencerCreate,
    InfluencerUpdate,
)
from app.shared.events.actions import DomainAction
from app.shared.permissions.roles import ActorType, Role

if TYPE_CHECKING:  # pragma: no cover - typing only
    from sqlalchemy.ext.asyncio import AsyncSession

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
    }
    data.update(overrides)
    return InfluencerCreate(**data)  # type: ignore[arg-type]


async def _actions(
    session: AsyncSession,
    tenant: Tenant,
    *,
    entity_id: object = None,
) -> list[str]:
    repository = AuditRepository(session)
    entries = await repository.list_entries(
        organization_id=tenant.organization.id,
        entity_id=entity_id,  # type: ignore[arg-type]
        limit=100,
    )
    return [entry.action for entry in entries]


# --- Emission ----------------------------------------------------------------


async def test_influencer_creation_is_audited(
    influencer_service: InfluencerService,
    session: AsyncSession,
    tenant: Tenant,
) -> None:
    influencer = await influencer_service.create(
        actor=tenant.actor(Role.OWNER),
        payload=_payload(),
    )
    actions = await _actions(session, tenant, entity_id=influencer.id)
    assert DomainAction.INFLUENCER_CREATED.value in actions


async def test_creation_entry_records_the_acting_user_and_role(
    influencer_service: InfluencerService,
    session: AsyncSession,
    tenant: Tenant,
) -> None:
    influencer = await influencer_service.create(
        actor=tenant.actor(Role.CREATIVE_LEAD),
        payload=_payload(),
    )
    entries = await AuditRepository(session).list_entries(
        organization_id=tenant.organization.id,
        entity_id=influencer.id,
    )
    entry = entries[-1]
    assert entry.actor_id == tenant.user(Role.CREATIVE_LEAD).id
    assert entry.actor_type is ActorType.USER
    assert entry.entity_type == Influencer.__name__
    assert entry.before_data is None
    assert entry.after_data is not None
    assert entry.after_data["code"] == "nora"


async def test_update_records_before_and_after(
    influencer_service: InfluencerService,
    session: AsyncSession,
    tenant: Tenant,
) -> None:
    actor = tenant.actor(Role.OWNER)
    influencer = await influencer_service.create(actor=actor, payload=_payload())
    await influencer_service.update(
        actor=actor,
        influencer_id=influencer.id,
        payload=InfluencerUpdate(public_name="Nora Prime"),
    )

    entries = await AuditRepository(session).list_entries(
        organization_id=tenant.organization.id,
        entity_id=influencer.id,
        action=DomainAction.INFLUENCER_UPDATED.value,
    )
    assert len(entries) == 1
    entry = entries[0]
    assert entry.before_data is not None
    assert entry.before_data["public_name"] == "Nora"
    assert entry.after_data is not None
    assert entry.after_data["public_name"] == "Nora Prime"
    assert diff(entry.before_data, entry.after_data)["public_name"] == {
        "from": "Nora",
        "to": "Nora Prime",
    }


async def test_status_change_is_audited_with_the_reason(
    influencer_service: InfluencerService,
    session: AsyncSession,
    tenant: Tenant,
) -> None:
    actor = tenant.actor(Role.OWNER)
    influencer = await influencer_service.create(actor=actor, payload=_payload())
    await influencer_service.change_status(
        actor=actor,
        influencer_id=influencer.id,
        target=InfluencerStatus.ARCHIVED,
        reason="Campaign finished",
    )
    entries = await AuditRepository(session).list_entries(
        organization_id=tenant.organization.id,
        entity_id=influencer.id,
        action=DomainAction.INFLUENCER_ARCHIVED.value,
    )
    assert len(entries) == 1
    after = entries[0].after_data
    assert after is not None
    assert after["status"] == InfluencerStatus.ARCHIVED.value
    assert after["transition_reason"] == "Campaign finished"


async def test_version_creation_writes_two_entries(
    influencer_service: InfluencerService,
    version_service: InfluencerVersionService,
    session: AsyncSession,
    tenant: Tenant,
) -> None:
    """One against the version, one against the influencer's own history tab."""
    actor = tenant.actor(Role.OWNER)
    influencer = await influencer_service.create(actor=actor, payload=_payload())
    version = await version_service.create_version(
        actor=actor,
        influencer_id=influencer.id,
        payload=InfluencerVersionCreate(change_summary="Initial identity"),
    )

    version_actions = await _actions(session, tenant, entity_id=version.id)
    assert version_actions == [DomainAction.INFLUENCER_VERSION_CREATED.value]

    influencer_actions = await _actions(session, tenant, entity_id=influencer.id)
    assert DomainAction.INFLUENCER_VERSION_PROMOTED.value in influencer_actions


async def test_policy_update_is_audited(
    influencer_service: InfluencerService,
    session: AsyncSession,
    tenant: Tenant,
) -> None:
    """Policies are mutable, so the audit entry is the historical record."""
    await influencer_service.update_policy(
        actor=tenant.actor(Role.COMPLIANCE),
        policy_id=tenant.policy.id,
        payload=DisclosurePolicyUpdate(ai_disclosure_text="Updated disclosure wording."),
    )
    entries = await AuditRepository(session).list_entries(
        organization_id=tenant.organization.id,
        entity_id=tenant.policy.id,
        action=DomainAction.DISCLOSURE_POLICY_UPDATED.value,
    )
    assert len(entries) == 1
    changed = diff(entries[0].before_data, entries[0].after_data)
    assert "ai_disclosure_text" in changed


async def test_a_refused_action_writes_no_entry(
    influencer_service: InfluencerService,
    session: AsyncSession,
    tenant: Tenant,
) -> None:
    with pytest.raises(PermissionDeniedError):
        await influencer_service.create(actor=tenant.actor(Role.ANALYST), payload=_payload())
    assert await _actions(session, tenant) == []


async def test_no_op_update_writes_no_entry(
    influencer_service: InfluencerService,
    session: AsyncSession,
    tenant: Tenant,
) -> None:
    """An empty patch is not a change, so it must not pollute the trail."""
    actor = tenant.actor(Role.OWNER)
    influencer = await influencer_service.create(actor=actor, payload=_payload())
    await influencer_service.update(
        actor=actor,
        influencer_id=influencer.id,
        payload=InfluencerUpdate(),
    )
    actions = await _actions(session, tenant, entity_id=influencer.id)
    assert actions == [DomainAction.INFLUENCER_CREATED.value]


async def test_system_actor_is_recorded_as_system(
    audit_service: AuditService,
    session: AsyncSession,
    tenant: Tenant,
) -> None:
    await audit_service.record(
        actor=CurrentActor.system(tenant.organization.id),
        action=DomainAction.ORGANIZATION_CREATED,
        entity_type="Organization",
        entity_id=tenant.organization.id,
        after_data={"slug": tenant.organization.slug},
    )
    entries = await AuditRepository(session).list_entries(
        organization_id=tenant.organization.id,
        actor_type=ActorType.SYSTEM,
    )
    assert len(entries) == 1
    assert entries[0].actor_id is None


# --- Isolation and shape -----------------------------------------------------


async def test_audit_entries_do_not_cross_organizations(
    influencer_service: InfluencerService,
    session: AsyncSession,
    tenant: Tenant,
    other_tenant: Tenant,
) -> None:
    await influencer_service.create(actor=tenant.actor(Role.OWNER), payload=_payload("ours"))
    await influencer_service.create(
        actor=other_tenant.actor(Role.OWNER),
        payload=_payload("theirs"),
    )
    repository = AuditRepository(session)
    ours = await repository.list_entries(organization_id=tenant.organization.id)
    theirs = await repository.list_entries(organization_id=other_tenant.organization.id)
    assert len(ours) == 1
    assert len(theirs) == 1
    assert ours[0].id != theirs[0].id


async def test_count_matches_the_filtered_list(
    influencer_service: InfluencerService,
    session: AsyncSession,
    tenant: Tenant,
) -> None:
    actor = tenant.actor(Role.OWNER)
    for index in range(3):
        await influencer_service.create(actor=actor, payload=_payload(f"nora-{index}"))

    repository = AuditRepository(session)
    entries = await repository.list_entries(
        organization_id=tenant.organization.id,
        action=DomainAction.INFLUENCER_CREATED.value,
        limit=2,
    )
    total = await repository.count_entries(
        organization_id=tenant.organization.id,
        action=DomainAction.INFLUENCER_CREATED.value,
    )
    assert len(entries) == 2
    assert total == 3


async def test_entries_are_returned_newest_first(
    influencer_service: InfluencerService,
    session: AsyncSession,
    tenant: Tenant,
) -> None:
    """Ordering must hold even for entries written in the same transaction.

    Both rows below share a `created_at` — PostgreSQL `now()` is the transaction
    timestamp — so this only passes because ordering uses `sequence_number`.
    """
    actor = tenant.actor(Role.OWNER)
    influencer = await influencer_service.create(actor=actor, payload=_payload())
    await influencer_service.update(
        actor=actor,
        influencer_id=influencer.id,
        payload=InfluencerUpdate(public_name="Second"),
    )
    entries = await AuditRepository(session).list_entries(
        organization_id=tenant.organization.id,
        entity_id=influencer.id,
    )
    assert [entry.action for entry in entries] == [
        DomainAction.INFLUENCER_UPDATED.value,
        DomainAction.INFLUENCER_CREATED.value,
    ]
    assert entries[0].created_at == entries[1].created_at
    assert entries[0].sequence_number > entries[1].sequence_number


def test_audit_table_is_append_only_in_shape() -> None:
    """No `updated_at`: an entry that could be edited is not an audit trail."""
    columns = {column.key for column in sa_inspect(AuditLog).mapper.column_attrs}
    assert "updated_at" not in columns


def test_audit_repository_has_no_write_methods() -> None:
    public = {
        name
        for name, _ in inspect.getmembers(AuditRepository, inspect.isfunction)
        if not name.startswith("_")
    }
    assert public == {"count_entries", "list_entries"}


# --- Serialisation -----------------------------------------------------------


async def test_snapshot_redacts_credentials(session: AsyncSession, tenant: Tenant) -> None:
    """A user snapshot must show that a credential exists, not what it is."""
    user = tenant.user(Role.OWNER)
    assert user.password_hash is not None
    data = snapshot(user)
    assert data["password_hash"] == REDACTED
    assert user.password_hash not in str(data)
    del session


def test_snapshot_is_json_safe() -> None:
    """UUIDs, datetimes and enums are converted, so JSONB accepts the row."""
    influencer = Influencer(
        id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        code="nora",
        public_name="Nora",
        status=InfluencerStatus.DRAFT,
        primary_language="en",
        primary_market="DE",
        adult_representation_confirmed=False,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    data = snapshot(influencer)
    json.dumps(data)  # must not raise
    assert data["status"] == "draft"
    assert isinstance(data["id"], str)


def test_diff_reports_only_changed_keys() -> None:
    changed = diff({"a": 1, "b": 2}, {"a": 1, "b": 3, "c": 4})
    assert changed == {"b": {"from": 2, "to": 3}, "c": {"from": None, "to": 4}}
