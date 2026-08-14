"""`/api/v1/organizations` routes."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, status

from app.api.deps import ActorDep, OrganizationServiceDep, RequirePermission
from app.modules.organizations.schemas import (
    MembershipRead,
    MembershipRoleUpdate,
    MembershipWithUserRead,
    OrganizationRead,
    OrganizationUpdate,
)
from app.shared.permissions.permissions import Permission

router = APIRouter(prefix="/organizations", tags=["organizations"])


@router.get(
    "/current",
    response_model=OrganizationRead,
    dependencies=[Depends(RequirePermission(Permission.ORG_READ))],
    summary="The organization the session is scoped to",
)
async def read_current_organization(
    actor: ActorDep,
    service: OrganizationServiceDep,
) -> OrganizationRead:
    organization = await service.get(actor=actor, organization_id=actor.organization_id)
    return OrganizationRead.model_validate(organization)


@router.patch(
    "/current",
    response_model=OrganizationRead,
    dependencies=[Depends(RequirePermission(Permission.ORG_UPDATE))],
    summary="Rename the current organization",
)
async def update_current_organization(
    payload: OrganizationUpdate,
    actor: ActorDep,
    service: OrganizationServiceDep,
) -> OrganizationRead:
    organization = await service.update(
        actor=actor,
        organization_id=actor.organization_id,
        name=payload.name,
    )
    return OrganizationRead.model_validate(organization)


@router.get(
    "/current/members",
    response_model=list[MembershipWithUserRead],
    dependencies=[Depends(RequirePermission(Permission.ORG_READ))],
    summary="List members of the current organization",
)
async def list_members(
    actor: ActorDep,
    service: OrganizationServiceDep,
) -> list[MembershipWithUserRead]:
    memberships = await service.list_members(actor=actor)
    return [
        MembershipWithUserRead(
            id=membership.id,
            organization_id=membership.organization_id,
            user_id=membership.user_id,
            role=membership.role,
            created_at=membership.created_at,
            user_email=membership.user.email,
            user_display_name=membership.user.display_name,
        )
        for membership in memberships
    ]


@router.patch(
    "/current/members/{user_id}",
    response_model=MembershipRead,
    dependencies=[Depends(RequirePermission(Permission.ORG_MEMBER_MANAGE))],
    summary="Change a member's role",
)
async def change_member_role(
    user_id: uuid.UUID,
    payload: MembershipRoleUpdate,
    actor: ActorDep,
    service: OrganizationServiceDep,
) -> MembershipRead:
    membership = await service.change_member_role(
        actor=actor,
        user_id=user_id,
        role=payload.role,
    )
    return MembershipRead.model_validate(membership)


@router.delete(
    "/current/members/{user_id}",
    status_code=status.HTTP_200_OK,
    response_model=MembershipRead,
    dependencies=[Depends(RequirePermission(Permission.ORG_MEMBER_MANAGE))],
    summary="Revoke a membership",
    description=(
        "Soft revocation. The membership row is retained so historical actions "
        "stay attributable; it simply stops granting access."
    ),
)
async def revoke_member(
    user_id: uuid.UUID,
    actor: ActorDep,
    service: OrganizationServiceDep,
) -> MembershipRead:
    membership = await service.revoke_member(actor=actor, user_id=user_id)
    return MembershipRead.model_validate(membership)
