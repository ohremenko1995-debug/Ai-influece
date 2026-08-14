"""`/api/v1/me` routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import ActorDep, get_membership_repository, get_user_repository
from app.core.errors import AuthenticationError
from app.modules.organizations.repository import MembershipRepository
from app.modules.users.repository import UserRepository
from app.modules.users.schemas import MembershipSummary, MeRead, UserRead

router = APIRouter(prefix="/me", tags=["me"])


@router.get(
    "",
    response_model=MeRead,
    summary="The current session: user, active organization, role and permissions",
)
async def read_me(
    actor: ActorDep,
    users: Annotated[UserRepository, Depends(get_user_repository)],
    memberships: Annotated[MembershipRepository, Depends(get_membership_repository)],
) -> MeRead:
    if actor.user_id is None or actor.role is None:  # pragma: no cover - defensive
        raise AuthenticationError("Session is not bound to a user")

    user = await users.get_by_id(actor.user_id)
    if user is None:  # pragma: no cover - the actor was just resolved from this row
        raise AuthenticationError("Account is not active", code="account_inactive")

    active = await memberships.list_active_for_user(user.id)
    return MeRead(
        user=UserRead.model_validate(user),
        active_organization_id=actor.organization_id,
        active_role=actor.role,
        actor_type=actor.actor_type,
        permissions=sorted(actor.permissions, key=lambda permission: permission.value),
        memberships=[
            MembershipSummary(
                organization_id=membership.organization_id,
                organization_name=membership.organization.name,
                organization_slug=membership.organization.slug,
                role=membership.role,
            )
            for membership in active
        ],
    )
