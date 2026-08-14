"""Authentication domain service."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.core.actor import CurrentActor
from app.core.config import Settings
from app.core.errors import AuthenticationError, PermissionDeniedError
from app.core.security import (
    TokenType,
    create_token,
    decode_token,
    hash_password,
    needs_rehash,
    verify_password,
)
from app.modules.audit.service import AuditService
from app.modules.auth.schemas import TokenPair
from app.modules.organizations.models import Membership
from app.modules.organizations.repository import MembershipRepository
from app.modules.users.models import User
from app.modules.users.repository import UserRepository
from app.shared.events.actions import DomainAction
from app.shared.observability.logging import get_logger

if TYPE_CHECKING:  # pragma: no cover - typing only
    from sqlalchemy.ext.asyncio import AsyncSession

_logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class AuthenticatedSession:
    """A verified identity bound to one organization."""

    user: User
    membership: Membership
    tokens: TokenPair


class AuthService:
    """Verifies credentials and issues tokens."""

    def __init__(
        self,
        *,
        session: AsyncSession,
        users: UserRepository,
        memberships: MembershipRepository,
        audit: AuditService,
        settings: Settings,
    ) -> None:
        self._session = session
        self._users = users
        self._memberships = memberships
        self._audit = audit
        self._settings = settings

    async def login(
        self,
        *,
        email: str,
        password: str,
        organization_id: uuid.UUID | None = None,
    ) -> AuthenticatedSession:
        """Password login."""
        user = await self._users.get_by_email(email)
        # Verify even when the user is missing, so the response time does not
        # reveal whether the address exists.
        password_ok = verify_password(password, user.password_hash if user else None)

        if user is None or not password_ok:
            await self._record_failed_login(email=email, user=user, reason="invalid_credentials")
            raise AuthenticationError("Email or password is incorrect")

        if not user.can_authenticate:
            await self._record_failed_login(email=email, user=user, reason="user_not_active")
            raise AuthenticationError("Account is not active", code="account_inactive")

        if user.password_hash is not None and needs_rehash(user.password_hash):
            # Transparent upgrade to current argon2 parameters.
            user.password_hash = hash_password(password)

        return await self._establish_session(
            user=user,
            organization_id=organization_id,
            action=DomainAction.AUTH_LOGIN_SUCCEEDED,
        )

    async def dev_login(
        self,
        *,
        email: str,
        organization_id: uuid.UUID | None = None,
    ) -> AuthenticatedSession:
        """Passwordless login for local development.

        Guarded by `Settings.dev_auth_active`, which requires *both*
        `DEV_AUTH_ENABLED=true` and `ENVIRONMENT=development`. The route itself is
        also omitted from the router outside development, so there are two
        independent barriers (docs/adr/0006-development-auth-stub.md).
        """
        if not self._settings.dev_auth_active:
            raise PermissionDeniedError(
                "Development authentication is disabled",
                code="dev_auth_disabled",
            )

        user = await self._users.get_by_email(email)
        if user is None:
            raise AuthenticationError(f"No user with email {email}", code="user_not_found")
        if not user.can_authenticate:
            raise AuthenticationError("Account is not active", code="account_inactive")

        return await self._establish_session(
            user=user,
            organization_id=organization_id,
            action=DomainAction.AUTH_DEV_LOGIN_USED,
        )

    async def refresh(self, *, refresh_token: str) -> AuthenticatedSession:
        """Exchange a refresh token for a new pair."""
        claims = decode_token(
            settings=self._settings,
            token=refresh_token,
            expected_type=TokenType.REFRESH,
        )
        user = await self._users.get_by_id(claims.subject)
        if user is None or not user.can_authenticate:
            raise AuthenticationError("Account is not active", code="account_inactive")

        return await self._establish_session(
            user=user,
            organization_id=claims.organization_id,
            action=DomainAction.AUTH_TOKEN_REFRESHED,
        )

    async def _establish_session(
        self,
        *,
        user: User,
        organization_id: uuid.UUID | None,
        action: DomainAction,
    ) -> AuthenticatedSession:
        membership = await self._resolve_membership(user=user, organization_id=organization_id)
        actor = CurrentActor.for_membership(
            organization_id=membership.organization_id,
            user_id=user.id,
            role=membership.role,
            email=user.email,
            display_name=user.display_name,
        )
        await self._audit.record(
            actor=actor,
            action=action,
            entity_type=User.__name__,
            entity_id=user.id,
            after_data={"email": user.email, "role": membership.role.value},
        )
        return AuthenticatedSession(
            user=user,
            membership=membership,
            tokens=self.issue_tokens(user=user, organization_id=membership.organization_id),
        )

    async def _resolve_membership(
        self,
        *,
        user: User,
        organization_id: uuid.UUID | None,
    ) -> Membership:
        """Pick the organization for this session.

        An explicit id must correspond to a live membership. Without one, the
        oldest membership is used, which makes single-organization logins simple
        while keeping multi-organization logins explicit.
        """
        if organization_id is not None:
            membership = await self._memberships.get_active(
                user_id=user.id,
                organization_id=organization_id,
            )
            if membership is None:
                raise PermissionDeniedError(
                    "You are not a member of that organization",
                    code="not_a_member",
                    details={"organization_id": str(organization_id)},
                )
            return membership

        memberships = await self._memberships.list_active_for_user(user.id)
        if not memberships:
            raise PermissionDeniedError(
                "User has no active organization membership",
                code="no_membership",
            )
        return memberships[0]

    def issue_tokens(self, *, user: User, organization_id: uuid.UUID) -> TokenPair:
        return TokenPair(
            access_token=create_token(
                settings=self._settings,
                subject=user.id,
                token_type=TokenType.ACCESS,
                organization_id=organization_id,
            ),
            refresh_token=create_token(
                settings=self._settings,
                subject=user.id,
                token_type=TokenType.REFRESH,
                organization_id=organization_id,
            ),
            expires_in_seconds=self._settings.access_token_ttl_minutes * 60,
            organization_id=organization_id,
        )

    async def _record_failed_login(
        self,
        *,
        email: str,
        user: User | None,
        reason: str,
    ) -> None:
        """Persist a failed attempt when it can be attributed to an organization.

        Committed immediately: the request is about to fail with 401, and the unit
        of work rolls back on exception, which would otherwise discard this row.
        A rollback after this commit is a no-op on a fresh transaction.

        Attempts against unknown addresses have no organization to file under, so
        they are logged rather than audited — see docs/security.md.
        """
        _logger.warning("auth_login_failed", email=email, reason=reason)
        if user is None:
            return

        memberships = await self._memberships.list_active_for_user(user.id)
        if not memberships:
            return

        membership = memberships[0]
        await self._audit.record(
            actor=CurrentActor.system(membership.organization_id),
            action=DomainAction.AUTH_LOGIN_FAILED,
            entity_type=User.__name__,
            entity_id=user.id,
            after_data={"email": user.email, "reason": reason},
        )
        await self._session.commit()
