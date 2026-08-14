"""Character Bible versioning tests.

The guarantees under test are the ones the whole traceability story rests on:
versions are append-only, numbering is gapless, exactly one version is current,
and the append-only property is enforced by the database, not only by convention.
"""

from __future__ import annotations

import inspect
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import inspect as sa_inspect
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.actor import CurrentActor
from app.core.errors import (
    ConflictError,
    DomainValidationError,
    NotFoundError,
    PermissionDeniedError,
)
from app.modules.character_versions.models import InfluencerVersion
from app.modules.character_versions.repository import InfluencerVersionRepository
from app.modules.character_versions.schemas import InfluencerVersionCreate
from app.modules.influencers.models import InfluencerStatus
from app.modules.influencers.schemas import InfluencerCreate
from app.shared.permissions.roles import Role

if TYPE_CHECKING:  # pragma: no cover - typing only
    import uuid

    from sqlalchemy.ext.asyncio import AsyncSession

    from app.modules.character_versions.service import InfluencerVersionService
    from app.modules.influencers.service import InfluencerService
    from tests.conftest import Tenant

pytestmark = pytest.mark.integration


def _bible(summary: str, **overrides: object) -> InfluencerVersionCreate:
    data: dict[str, object] = {
        "change_summary": summary,
        "biography": "A virtual coach.",
        "tone_of_voice": "Warm.",
        "personality_traits": ["disciplined"],
        "prohibited_topics": ["medical advice"],
        "visual_constraints": {"eye_color": "green"},
        "speech_constraints": {"max_wpm": 165},
    }
    data.update(overrides)
    return InfluencerVersionCreate(**data)  # type: ignore[arg-type]


async def _influencer(service: InfluencerService, tenant: Tenant, code: str = "nora") -> uuid.UUID:
    influencer = await service.create(
        actor=tenant.actor(Role.OWNER),
        payload=InfluencerCreate(
            code=code,
            public_name="Nora",
            primary_language="en",
            primary_market="DE",
        ),
    )
    return influencer.id


# --- Numbering and currency --------------------------------------------------


async def test_first_version_is_number_one_and_current(
    influencer_service: InfluencerService,
    version_service: InfluencerVersionService,
    tenant: Tenant,
) -> None:
    influencer_id = await _influencer(influencer_service, tenant)
    version = await version_service.create_version(
        actor=tenant.actor(Role.OWNER),
        influencer_id=influencer_id,
        payload=_bible("Initial identity"),
    )
    assert version.version_number == 1
    assert version.is_current is True
    assert version.created_by == tenant.user(Role.OWNER).id


async def test_versions_are_numbered_without_gaps(
    influencer_service: InfluencerService,
    version_service: InfluencerVersionService,
    tenant: Tenant,
) -> None:
    influencer_id = await _influencer(influencer_service, tenant)
    actor = tenant.actor(Role.OWNER)
    for index in range(1, 5):
        version = await version_service.create_version(
            actor=actor,
            influencer_id=influencer_id,
            payload=_bible(f"Revision {index}"),
        )
        assert version.version_number == index


async def test_only_the_newest_version_is_current(
    influencer_service: InfluencerService,
    version_service: InfluencerVersionService,
    session: AsyncSession,
    tenant: Tenant,
) -> None:
    influencer_id = await _influencer(influencer_service, tenant)
    actor = tenant.actor(Role.OWNER)
    await version_service.create_version(
        actor=actor, influencer_id=influencer_id, payload=_bible("Revision one")
    )
    await version_service.create_version(
        actor=actor, influencer_id=influencer_id, payload=_bible("Revision two")
    )
    third = await version_service.create_version(
        actor=actor, influencer_id=influencer_id, payload=_bible("Revision three")
    )

    result = await session.execute(
        select(InfluencerVersion).where(
            InfluencerVersion.influencer_id == influencer_id,
            InfluencerVersion.is_current.is_(True),
        )
    )
    current = result.scalars().all()
    assert len(current) == 1
    assert current[0].id == third.id


async def test_earlier_versions_stay_readable(
    influencer_service: InfluencerService,
    version_service: InfluencerVersionService,
    tenant: Tenant,
) -> None:
    """Superseding an identity must never destroy the one that came before."""
    influencer_id = await _influencer(influencer_service, tenant)
    actor = tenant.actor(Role.OWNER)
    await version_service.create_version(
        actor=actor,
        influencer_id=influencer_id,
        payload=_bible("Revision one", prohibited_topics=["politics"]),
    )
    await version_service.create_version(
        actor=actor,
        influencer_id=influencer_id,
        payload=_bible("Revision two", prohibited_topics=["politics", "religion"]),
    )

    first = await version_service.get_version(
        actor=actor,
        influencer_id=influencer_id,
        version_number=1,
    )
    assert first.prohibited_topics == ["politics"]
    assert first.is_current is False

    items, total = await version_service.list_versions(actor=actor, influencer_id=influencer_id)
    assert total == 2
    assert [item.version_number for item in items] == [2, 1]


async def test_current_version_lookup_fails_before_any_version_exists(
    influencer_service: InfluencerService,
    version_service: InfluencerVersionService,
    tenant: Tenant,
) -> None:
    influencer_id = await _influencer(influencer_service, tenant)
    with pytest.raises(NotFoundError) as exc_info:
        await version_service.get_current(
            actor=tenant.actor(Role.OWNER),
            influencer_id=influencer_id,
        )
    assert exc_info.value.code == "no_current_version"


# --- Immutability ------------------------------------------------------------


def test_repository_exposes_no_mutating_operation() -> None:
    """Append-only is a property of the code surface, not a convention.

    If someone adds an `update`/`delete`/`save` method to the version repository,
    this fails — which is the point: the only legitimate way to change an identity
    is to append a new version.
    """
    public = {
        name
        for name, member in inspect.getmembers(InfluencerVersionRepository, inspect.isfunction)
        if not name.startswith("_")
    }
    forbidden = {name for name in public if name.startswith(("update", "delete", "remove", "save"))}
    assert forbidden == set()
    assert public == {
        "count_for_influencer",
        "create",
        "demote_current",
        "get_by_id",
        "get_by_number",
        "get_current",
        "list_for_influencer",
        "next_version_number",
    }


async def test_database_rejects_a_duplicate_version_number(
    influencer_service: InfluencerService,
    version_service: InfluencerVersionService,
    session: AsyncSession,
    tenant: Tenant,
) -> None:
    """The unique constraint, not just the service, guarantees numbering."""
    influencer_id = await _influencer(influencer_service, tenant)
    await version_service.create_version(
        actor=tenant.actor(Role.OWNER),
        influencer_id=influencer_id,
        payload=_bible("Revision one"),
    )
    session.add(
        InfluencerVersion(
            influencer_id=influencer_id,
            version_number=1,
            change_summary="Smuggled duplicate",
            created_by=tenant.user(Role.OWNER).id,
            personality_traits=[],
            prohibited_topics=[],
            visual_constraints={},
            speech_constraints={},
            is_current=False,
        )
    )
    with pytest.raises(IntegrityError):
        await session.flush()
    await session.rollback()


async def test_database_rejects_two_current_versions(
    influencer_service: InfluencerService,
    version_service: InfluencerVersionService,
    session: AsyncSession,
    tenant: Tenant,
) -> None:
    """The partial unique index enforces a single current version."""
    influencer_id = await _influencer(influencer_service, tenant)
    await version_service.create_version(
        actor=tenant.actor(Role.OWNER),
        influencer_id=influencer_id,
        payload=_bible("Revision one"),
    )
    session.add(
        InfluencerVersion(
            influencer_id=influencer_id,
            version_number=2,
            change_summary="Second current version",
            created_by=tenant.user(Role.OWNER).id,
            personality_traits=[],
            prohibited_topics=[],
            visual_constraints={},
            speech_constraints={},
            is_current=True,
        )
    )
    with pytest.raises(IntegrityError):
        await session.flush()
    await session.rollback()


async def test_version_number_must_be_positive(
    influencer_service: InfluencerService,
    session: AsyncSession,
    tenant: Tenant,
) -> None:
    influencer_id = await _influencer(influencer_service, tenant)
    session.add(
        InfluencerVersion(
            influencer_id=influencer_id,
            version_number=0,
            change_summary="Zeroth",
            created_by=tenant.user(Role.OWNER).id,
            personality_traits=[],
            prohibited_topics=[],
            visual_constraints={},
            speech_constraints={},
            is_current=False,
        )
    )
    with pytest.raises(IntegrityError):
        await session.flush()
    await session.rollback()


async def test_stored_snapshot_matches_the_submitted_payload(
    influencer_service: InfluencerService,
    version_service: InfluencerVersionService,
    session: AsyncSession,
    tenant: Tenant,
) -> None:
    """JSONB round-trips unchanged, so a historical read is exact."""
    influencer_id = await _influencer(influencer_service, tenant)
    payload = _bible(
        "Full snapshot",
        personality_traits=["a", "b", "c"],
        visual_constraints={"nested": {"depth": 2}, "list": [1, 2, 3]},
    )
    version = await version_service.create_version(
        actor=tenant.actor(Role.OWNER),
        influencer_id=influencer_id,
        payload=payload,
    )
    # Re-read the columns from PostgreSQL rather than trusting the in-memory
    # object, so this actually exercises the JSONB round trip.
    await session.refresh(version)
    assert version.personality_traits == ["a", "b", "c"]
    assert version.visual_constraints == {"nested": {"depth": 2}, "list": [1, 2, 3]}
    assert version.prohibited_topics == ["medical advice"]


def test_version_model_has_no_updated_at() -> None:
    """An append-only row has no meaningful `updated_at`."""
    columns = {column.key for column in sa_inspect(InfluencerVersion).mapper.column_attrs}
    assert "updated_at" not in columns
    assert "created_at" in columns


# --- Authorization and preconditions ----------------------------------------


@pytest.mark.parametrize("role", [Role.OPERATOR, Role.REVIEWER, Role.ANALYST, Role.AGENT])
async def test_roles_without_version_permission_are_refused(
    influencer_service: InfluencerService,
    version_service: InfluencerVersionService,
    tenant: Tenant,
    role: Role,
) -> None:
    influencer_id = await _influencer(influencer_service, tenant)
    with pytest.raises(PermissionDeniedError):
        await version_service.create_version(
            actor=tenant.actor(role),
            influencer_id=influencer_id,
            payload=_bible("Unauthorised"),
        )


async def test_versions_cannot_be_appended_to_another_organizations_influencer(
    influencer_service: InfluencerService,
    version_service: InfluencerVersionService,
    tenant: Tenant,
    other_tenant: Tenant,
) -> None:
    influencer_id = await _influencer(influencer_service, tenant)
    with pytest.raises(NotFoundError):
        await version_service.create_version(
            actor=other_tenant.actor(Role.OWNER),
            influencer_id=influencer_id,
            payload=_bible("Cross-tenant"),
        )


async def test_archived_influencers_reject_new_versions(
    influencer_service: InfluencerService,
    version_service: InfluencerVersionService,
    tenant: Tenant,
) -> None:
    actor = tenant.actor(Role.OWNER)
    influencer_id = await _influencer(influencer_service, tenant)
    await influencer_service.change_status(
        actor=actor,
        influencer_id=influencer_id,
        target=InfluencerStatus.ARCHIVED,
    )
    with pytest.raises(ConflictError) as exc_info:
        await version_service.create_version(
            actor=actor,
            influencer_id=influencer_id,
            payload=_bible("After archival"),
        )
    assert exc_info.value.code == "influencer_archived"


async def test_system_actor_cannot_author_an_identity_revision(
    influencer_service: InfluencerService,
    version_service: InfluencerVersionService,
    tenant: Tenant,
) -> None:
    """`created_by` must name a real person; identity edits are not automatable."""
    influencer_id = await _influencer(influencer_service, tenant)
    with pytest.raises(DomainValidationError) as exc_info:
        await version_service.create_version(
            actor=CurrentActor.system(tenant.organization.id),
            influencer_id=influencer_id,
            payload=_bible("By the system"),
        )
    assert exc_info.value.code == "user_actor_required"


def test_duplicate_traits_are_rejected_by_the_schema() -> None:
    with pytest.raises(ValueError, match="unique"):
        _bible("dupes", personality_traits=["Calm", "calm"])
