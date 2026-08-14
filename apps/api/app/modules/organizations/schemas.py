"""Organization and membership request/response models."""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Annotated

from pydantic import EmailStr, Field, field_validator

from app.api.schemas import ApiModel, RequestModel
from app.shared.permissions.roles import Role

SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

SlugStr = Annotated[str, Field(min_length=2, max_length=100)]


class OrganizationRead(ApiModel):
    id: uuid.UUID
    name: str
    slug: str
    created_at: datetime
    updated_at: datetime


class OrganizationCreate(RequestModel):
    name: str = Field(min_length=2, max_length=200)
    slug: SlugStr | None = Field(
        default=None,
        description="URL-safe identifier. Derived from the name when omitted.",
    )

    @field_validator("slug")
    @classmethod
    def _validate_slug(cls, value: str | None) -> str | None:
        if value is not None and not SLUG_PATTERN.fullmatch(value):
            msg = "slug must be lowercase alphanumeric words separated by single hyphens"
            raise ValueError(msg)
        return value


class OrganizationUpdate(RequestModel):
    name: str | None = Field(default=None, min_length=2, max_length=200)


class MembershipRead(ApiModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    user_id: uuid.UUID
    role: Role
    created_at: datetime


class MembershipWithUserRead(MembershipRead):
    """Membership joined with enough user detail to render a members table."""

    user_email: EmailStr
    user_display_name: str


class MembershipCreate(RequestModel):
    user_id: uuid.UUID
    role: Role


class MembershipRoleUpdate(RequestModel):
    role: Role
