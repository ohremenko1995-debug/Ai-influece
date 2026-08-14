"""Password hashing and JWT issuing/verification.

Deliberately small: argon2id for passwords, HS256 JWTs for sessions. There is no
server-side session store on the MVP, so tokens cannot be revoked before expiry —
see docs/adr/0006-development-auth-stub.md and docs/security.md.
"""

from __future__ import annotations

import enum
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Final

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from app.core.config import Settings
from app.core.errors import AuthenticationError

_hasher: Final = PasswordHasher()

# A constant-cost verification target used when the account does not exist, so
# that "unknown email" and "wrong password" take comparable time.
_DUMMY_HASH: Final = _hasher.hash("influenceros-timing-equaliser")


class TokenType(enum.StrEnum):
    """Which kind of token a JWT is. Carried in the `typ` claim and checked on
    decode, so a refresh token cannot be presented as an access token."""

    ACCESS = "access"
    REFRESH = "refresh"


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    """Verify a password, taking a similar amount of work when no hash exists."""
    target = password_hash or _DUMMY_HASH
    try:
        _hasher.verify(target, password)
    except (VerifyMismatchError, InvalidHashError):
        return False
    return password_hash is not None


def needs_rehash(password_hash: str) -> bool:
    """True when the stored hash uses outdated argon2 parameters."""
    try:
        return _hasher.check_needs_rehash(password_hash)
    except InvalidHashError:
        return True


def create_token(
    *,
    settings: Settings,
    subject: uuid.UUID,
    token_type: TokenType,
    organization_id: uuid.UUID | None = None,
) -> str:
    """Issue a signed JWT for `subject`."""
    ttl = (
        settings.access_token_ttl_minutes
        if token_type is TokenType.ACCESS
        else settings.refresh_token_ttl_minutes
    )
    issued_at = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": str(subject),
        "typ": token_type.value,
        "iat": issued_at,
        "exp": issued_at + timedelta(minutes=ttl),
        "jti": str(uuid.uuid4()),
    }
    if organization_id is not None:
        payload["org"] = str(organization_id)
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


class TokenClaims:
    """Validated JWT claims."""

    __slots__ = ("organization_id", "subject", "token_type")

    def __init__(
        self,
        *,
        subject: uuid.UUID,
        token_type: TokenType,
        organization_id: uuid.UUID | None,
    ) -> None:
        self.subject = subject
        self.token_type = token_type
        self.organization_id = organization_id


def decode_token(*, settings: Settings, token: str, expected_type: TokenType) -> TokenClaims:
    """Decode and validate a JWT, or raise `AuthenticationError`."""
    try:
        payload: dict[str, Any] = jwt.decode(
            token,
            settings.secret_key,
            algorithms=[settings.jwt_algorithm],
            options={"require": ["exp", "iat", "sub", "jti"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise AuthenticationError("Token has expired", code="token_expired") from exc
    except jwt.InvalidTokenError as exc:
        raise AuthenticationError("Token is invalid", code="token_invalid") from exc

    raw_type = payload.get("typ")
    if raw_type != expected_type.value:
        raise AuthenticationError(
            f"Expected a {expected_type.value} token", code="token_wrong_type"
        )

    try:
        subject = uuid.UUID(str(payload["sub"]))
    except (KeyError, ValueError) as exc:
        raise AuthenticationError("Token subject is malformed", code="token_invalid") from exc

    organization_id: uuid.UUID | None = None
    raw_org = payload.get("org")
    if raw_org is not None:
        try:
            organization_id = uuid.UUID(str(raw_org))
        except ValueError as exc:
            raise AuthenticationError(
                "Token organization claim is malformed", code="token_invalid"
            ) from exc

    return TokenClaims(
        subject=subject,
        token_type=expected_type,
        organization_id=organization_id,
    )
