"""Authentication request/response models."""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import EmailStr, Field

from app.api.schemas import ApiModel, RequestModel


class LoginRequest(RequestModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256, repr=False)


class DevLoginRequest(RequestModel):
    """Passwordless login, available only when `Settings.dev_auth_active` is true."""

    email: EmailStr
    organization_id: uuid.UUID | None = Field(
        default=None,
        description="Organization to sign into. Defaults to the oldest membership.",
    )


class RefreshRequest(RequestModel):
    refresh_token: str = Field(min_length=1, repr=False)


class TokenPair(ApiModel):
    """Issued credentials.

    Tokens are stateless JWTs — there is no server-side revocation list on the
    MVP, so a leaked token is valid until it expires. Access TTL is kept short for
    that reason (docs/security.md).
    """

    access_token: str
    refresh_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in_seconds: int = Field(description="Lifetime of the access token")
    organization_id: uuid.UUID = Field(description="Organization the session is scoped to")
