"""User and `/me` response models."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import EmailStr, Field

from app.api.schemas import ApiModel
from app.modules.users.models import UserStatus
from app.shared.permissions.permissions import Permission
from app.shared.permissions.roles import ActorType, Role


class UserRead(ApiModel):
    """A user. Never carries credential material."""

    id: uuid.UUID
    email: EmailStr
    display_name: str
    status: UserStatus
    created_at: datetime
    updated_at: datetime


class MembershipSummary(ApiModel):
    """One of the caller's organization memberships."""

    organization_id: uuid.UUID
    organization_name: str
    organization_slug: str
    role: Role


class MeRead(ApiModel):
    """Everything the frontend needs to render a session.

    `permissions` is the resolved effective set for the *active* organization, so
    the UI can hide affordances the backend would refuse anyway. It is a
    convenience, not the enforcement point — every endpoint re-checks.
    """

    user: UserRead
    active_organization_id: uuid.UUID
    active_role: Role
    actor_type: ActorType
    permissions: list[Permission] = Field(
        description="Effective permissions in the active organization"
    )
    memberships: list[MembershipSummary]
