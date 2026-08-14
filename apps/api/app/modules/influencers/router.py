"""`/api/v1/influencers` and `/api/v1/disclosure-policies` routes."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, status

from app.api.deps import (
    ActorDep,
    AuditRepositoryDep,
    InfluencerServiceDep,
    RequirePermission,
    VersionServiceDep,
)
from app.api.schemas import DEFAULT_PAGE_SIZE, LimitQuery, OffsetQuery, Page
from app.modules.audit.schemas import AuditLogDiff, AuditLogRead
from app.modules.audit.serialization import diff
from app.modules.character_versions.schemas import InfluencerVersionCreate, InfluencerVersionRead
from app.modules.influencers.models import Influencer, InfluencerStatus
from app.modules.influencers.schemas import (
    DisclosurePolicyCreate,
    DisclosurePolicyRead,
    DisclosurePolicyUpdate,
    InfluencerCreate,
    InfluencerDetail,
    InfluencerRead,
    InfluencerStatusChange,
    InfluencerUpdate,
)
from app.modules.influencers.service import InfluencerService
from app.shared.permissions.permissions import Permission

router = APIRouter(prefix="/influencers", tags=["influencers"])
policies_router = APIRouter(prefix="/disclosure-policies", tags=["disclosure-policies"])


async def _to_detail(service: InfluencerService, influencer: Influencer) -> InfluencerDetail:
    """Detail projection, including why activation is blocked (if it is)."""
    detail = InfluencerDetail.model_validate(influencer)
    if influencer.disclosure_policy is not None:
        detail.disclosure_policy = DisclosurePolicyRead.model_validate(influencer.disclosure_policy)
    detail.activation_blockers = await service.activation_blockers(influencer)
    return detail


# --- Influencers ------------------------------------------------------------


@router.get(
    "",
    response_model=Page[InfluencerRead],
    dependencies=[Depends(RequirePermission(Permission.INFLUENCER_READ))],
    summary="List influencers",
)
async def list_influencers(
    actor: ActorDep,
    service: InfluencerServiceDep,
    status_filter: Annotated[
        list[InfluencerStatus] | None,
        Query(alias="status", description="Repeatable. Omit to hide archived characters."),
    ] = None,
    search: Annotated[str | None, Query(max_length=200)] = None,
    include_archived: Annotated[bool, Query()] = False,
    limit: Annotated[LimitQuery, Query()] = DEFAULT_PAGE_SIZE,
    offset: Annotated[OffsetQuery, Query()] = 0,
) -> Page[InfluencerRead]:
    items, total = await service.list_influencers(
        actor=actor,
        statuses=status_filter,
        search=search,
        include_archived=include_archived,
        limit=limit,
        offset=offset,
    )
    return Page[InfluencerRead](
        items=[InfluencerRead.model_validate(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "",
    response_model=InfluencerDetail,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(RequirePermission(Permission.INFLUENCER_CREATE))],
    summary="Create an influencer",
    description=(
        "Created in `draft`. Activation requires an adult-representation "
        "confirmation, a disclosure policy and a Character Bible version."
    ),
)
async def create_influencer(
    payload: InfluencerCreate,
    actor: ActorDep,
    service: InfluencerServiceDep,
) -> InfluencerDetail:
    influencer = await service.create(actor=actor, payload=payload)
    return await _to_detail(service, influencer)


@router.get(
    "/{influencer_id}",
    response_model=InfluencerDetail,
    dependencies=[Depends(RequirePermission(Permission.INFLUENCER_READ))],
    summary="Read one influencer",
)
async def read_influencer(
    influencer_id: uuid.UUID,
    actor: ActorDep,
    service: InfluencerServiceDep,
    versions: VersionServiceDep,
) -> InfluencerDetail:
    influencer = await service.get(actor=actor, influencer_id=influencer_id)
    detail = await _to_detail(service, influencer)
    current, _ = await versions.list_versions(
        actor=actor,
        influencer_id=influencer_id,
        limit=1,
        offset=0,
    )
    if current:
        detail.current_version_number = current[0].version_number
    return detail


@router.patch(
    "/{influencer_id}",
    response_model=InfluencerDetail,
    dependencies=[Depends(RequirePermission(Permission.INFLUENCER_UPDATE))],
    summary="Update an influencer",
)
async def update_influencer(
    influencer_id: uuid.UUID,
    payload: InfluencerUpdate,
    actor: ActorDep,
    service: InfluencerServiceDep,
) -> InfluencerDetail:
    influencer = await service.update(
        actor=actor,
        influencer_id=influencer_id,
        payload=payload,
    )
    return await _to_detail(service, influencer)


@router.post(
    "/{influencer_id}/status",
    response_model=InfluencerDetail,
    dependencies=[Depends(RequirePermission(Permission.INFLUENCER_READ))],
    summary="Move an influencer through its lifecycle",
    description=(
        "Transitions are validated by the backend state machine: "
        "draft→active|archived, active→paused|archived, paused→active|archived. "
        "`archived` is terminal."
    ),
)
async def change_influencer_status(
    influencer_id: uuid.UUID,
    payload: InfluencerStatusChange,
    actor: ActorDep,
    service: InfluencerServiceDep,
) -> InfluencerDetail:
    influencer = await service.change_status(
        actor=actor,
        influencer_id=influencer_id,
        target=payload.status,
        reason=payload.reason,
    )
    return await _to_detail(service, influencer)


# --- Character Bible versions ------------------------------------------------


@router.get(
    "/{influencer_id}/versions",
    response_model=Page[InfluencerVersionRead],
    dependencies=[Depends(RequirePermission(Permission.INFLUENCER_READ))],
    summary="List Character Bible versions, newest first",
)
async def list_versions(
    influencer_id: uuid.UUID,
    actor: ActorDep,
    service: VersionServiceDep,
    limit: Annotated[LimitQuery, Query()] = DEFAULT_PAGE_SIZE,
    offset: Annotated[OffsetQuery, Query()] = 0,
) -> Page[InfluencerVersionRead]:
    items, total = await service.list_versions(
        actor=actor,
        influencer_id=influencer_id,
        limit=limit,
        offset=offset,
    )
    return Page[InfluencerVersionRead](
        items=[InfluencerVersionRead.model_validate(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/{influencer_id}/versions",
    response_model=InfluencerVersionRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(RequirePermission(Permission.INFLUENCER_VERSION_CREATE))],
    summary="Append a Character Bible version",
    description=(
        "Versions are immutable. This creates version N+1 with the submitted "
        "snapshot and makes it current; earlier versions stay readable forever."
    ),
)
async def create_version(
    influencer_id: uuid.UUID,
    payload: InfluencerVersionCreate,
    actor: ActorDep,
    service: VersionServiceDep,
) -> InfluencerVersionRead:
    version = await service.create_version(
        actor=actor,
        influencer_id=influencer_id,
        payload=payload,
    )
    return InfluencerVersionRead.model_validate(version)


@router.get(
    "/{influencer_id}/versions/current",
    response_model=InfluencerVersionRead,
    dependencies=[Depends(RequirePermission(Permission.INFLUENCER_READ))],
    summary="Read the current Character Bible version",
)
async def read_current_version(
    influencer_id: uuid.UUID,
    actor: ActorDep,
    service: VersionServiceDep,
) -> InfluencerVersionRead:
    version = await service.get_current(actor=actor, influencer_id=influencer_id)
    return InfluencerVersionRead.model_validate(version)


@router.get(
    "/{influencer_id}/versions/{version_number}",
    response_model=InfluencerVersionRead,
    dependencies=[Depends(RequirePermission(Permission.INFLUENCER_READ))],
    summary="Read a specific Character Bible version",
)
async def read_version(
    influencer_id: uuid.UUID,
    version_number: Annotated[int, Path(ge=1)],
    actor: ActorDep,
    service: VersionServiceDep,
) -> InfluencerVersionRead:
    version = await service.get_version(
        actor=actor,
        influencer_id=influencer_id,
        version_number=version_number,
    )
    return InfluencerVersionRead.model_validate(version)


@router.get(
    "/{influencer_id}/audit-logs",
    response_model=Page[AuditLogDiff],
    dependencies=[Depends(RequirePermission(Permission.AUDIT_READ))],
    summary="History tab for one influencer",
    description=(
        "Same shape as `GET /audit-logs`, pre-filtered to this influencer. "
        "Entries carry a computed field-level diff for rendering the history tab."
    ),
)
async def read_influencer_history(
    influencer_id: uuid.UUID,
    actor: ActorDep,
    service: InfluencerServiceDep,
    audit: AuditRepositoryDep,
    limit: Annotated[LimitQuery, Query()] = DEFAULT_PAGE_SIZE,
    offset: Annotated[OffsetQuery, Query()] = 0,
) -> Page[AuditLogDiff]:
    # Confirms tenancy before exposing any audit rows for this id.
    await service.get(actor=actor, influencer_id=influencer_id)
    entries = await audit.list_entries(
        organization_id=actor.organization_id,
        entity_type=Influencer.__name__,
        entity_id=influencer_id,
        limit=limit,
        offset=offset,
    )
    total = await audit.count_entries(
        organization_id=actor.organization_id,
        entity_type=Influencer.__name__,
        entity_id=influencer_id,
    )
    return Page[AuditLogDiff](
        items=[
            AuditLogDiff(
                entry=AuditLogRead.model_validate(entry),
                changed_fields=(
                    diff(entry.before_data, entry.after_data)
                    if entry.before_data is not None
                    else {}
                ),
            )
            for entry in entries
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


# --- Disclosure policies -----------------------------------------------------


@policies_router.get(
    "",
    response_model=list[DisclosurePolicyRead],
    dependencies=[Depends(RequirePermission(Permission.POLICY_READ))],
    summary="List disclosure policies",
)
async def list_policies(
    actor: ActorDep,
    service: InfluencerServiceDep,
) -> list[DisclosurePolicyRead]:
    policies = await service.list_policies(actor=actor)
    return [DisclosurePolicyRead.model_validate(policy) for policy in policies]


@policies_router.post(
    "",
    response_model=DisclosurePolicyRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(RequirePermission(Permission.POLICY_UPDATE))],
    summary="Create a disclosure policy",
)
async def create_policy(
    payload: DisclosurePolicyCreate,
    actor: ActorDep,
    service: InfluencerServiceDep,
) -> DisclosurePolicyRead:
    policy = await service.create_policy(actor=actor, payload=payload)
    return DisclosurePolicyRead.model_validate(policy)


@policies_router.patch(
    "/{policy_id}",
    response_model=DisclosurePolicyRead,
    dependencies=[Depends(RequirePermission(Permission.POLICY_UPDATE))],
    summary="Update a disclosure policy",
    description=(
        "Policies are mutable and every change is audited with before/after data. "
        "Approved content keeps the disclosure text it was approved with."
    ),
)
async def update_policy(
    policy_id: uuid.UUID,
    payload: DisclosurePolicyUpdate,
    actor: ActorDep,
    service: InfluencerServiceDep,
) -> DisclosurePolicyRead:
    policy = await service.update_policy(
        actor=actor,
        policy_id=policy_id,
        payload=payload,
    )
    return DisclosurePolicyRead.model_validate(policy)
