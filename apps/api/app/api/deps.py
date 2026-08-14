"""FastAPI dependencies.

Wiring only — no business rules. Each dependency resolves one collaborator
(settings, session, repository, service) or the acting identity. Authorization is
declared per route with `RequirePermission`, and re-checked inside the services
themselves so a non-HTTP caller cannot bypass it.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Header, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.actor import CurrentActor
from app.core.config import Settings, get_settings
from app.core.context import set_actor
from app.core.errors import AuthenticationError, PermissionDeniedError
from app.core.security import TokenType, decode_token
from app.modules.audit.repository import AuditRepository
from app.modules.audit.service import AuditService
from app.modules.auth.service import AuthService
from app.modules.character_versions.repository import InfluencerVersionRepository
from app.modules.character_versions.service import InfluencerVersionService
from app.modules.influencers.repository import DisclosurePolicyRepository, InfluencerRepository
from app.modules.influencers.service import InfluencerService
from app.modules.organizations.repository import MembershipRepository, OrganizationRepository
from app.modules.organizations.service import OrganizationService
from app.modules.users.repository import UserRepository
from app.shared.db.session import Database
from app.shared.permissions.permissions import Permission

# `auto_error=False` so a missing header produces our own error envelope rather
# than FastAPI's default 403 body.
_bearer_scheme = HTTPBearer(auto_error=False, description="JWT access token")

ORGANIZATION_HEADER = "X-Organization-Id"


# --- Infrastructure ---------------------------------------------------------


def get_app_settings(request: Request) -> Settings:
    """The settings this application was built with.

    Read from `app.state`, not from the process-global cache: `create_app` accepts
    an explicit `Settings`, and a dependency that ignored it would sign tokens
    with a different key than the one the application was configured with.
    """
    settings = getattr(request.app.state, "settings", None)
    if isinstance(settings, Settings):
        return settings
    return get_settings()  # pragma: no cover - only if state was never populated


SettingsDep = Annotated[Settings, Depends(get_app_settings)]


def get_db(request: Request) -> Database:
    """The `Database` created during lifespan startup."""
    database = getattr(request.app.state, "database", None)
    if not isinstance(database, Database):  # pragma: no cover - misconfiguration
        msg = "Database is not initialised on app.state"
        raise RuntimeError(msg)
    return database


async def get_session(
    database: Annotated[Database, Depends(get_db)],
) -> AsyncIterator[AsyncSession]:
    """One unit of work per request.

    Commits when the handler returns, rolls back when it raises. Services never
    commit, which is what keeps a change and its audit row atomic.
    """
    async with database.session() as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_session)]


# --- Repositories -----------------------------------------------------------


def get_user_repository(session: SessionDep) -> UserRepository:
    return UserRepository(session)


def get_organization_repository(session: SessionDep) -> OrganizationRepository:
    return OrganizationRepository(session)


def get_membership_repository(session: SessionDep) -> MembershipRepository:
    return MembershipRepository(session)


def get_influencer_repository(session: SessionDep) -> InfluencerRepository:
    return InfluencerRepository(session)


def get_policy_repository(session: SessionDep) -> DisclosurePolicyRepository:
    return DisclosurePolicyRepository(session)


def get_version_repository(session: SessionDep) -> InfluencerVersionRepository:
    return InfluencerVersionRepository(session)


def get_audit_repository(session: SessionDep) -> AuditRepository:
    return AuditRepository(session)


AuditRepositoryDep = Annotated[AuditRepository, Depends(get_audit_repository)]


# --- Services ---------------------------------------------------------------


def get_audit_service(session: SessionDep) -> AuditService:
    return AuditService(session)


AuditServiceDep = Annotated[AuditService, Depends(get_audit_service)]


def get_auth_service(
    session: SessionDep,
    settings: SettingsDep,
    users: Annotated[UserRepository, Depends(get_user_repository)],
    memberships: Annotated[MembershipRepository, Depends(get_membership_repository)],
    audit: AuditServiceDep,
) -> AuthService:
    return AuthService(
        session=session,
        users=users,
        memberships=memberships,
        audit=audit,
        settings=settings,
    )


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]


def get_organization_service(
    organizations: Annotated[OrganizationRepository, Depends(get_organization_repository)],
    memberships: Annotated[MembershipRepository, Depends(get_membership_repository)],
    audit: AuditServiceDep,
) -> OrganizationService:
    return OrganizationService(
        organizations=organizations,
        memberships=memberships,
        audit=audit,
    )


OrganizationServiceDep = Annotated[OrganizationService, Depends(get_organization_service)]


def get_influencer_service(
    influencers: Annotated[InfluencerRepository, Depends(get_influencer_repository)],
    policies: Annotated[DisclosurePolicyRepository, Depends(get_policy_repository)],
    versions: Annotated[InfluencerVersionRepository, Depends(get_version_repository)],
    audit: AuditServiceDep,
) -> InfluencerService:
    return InfluencerService(
        influencers=influencers,
        policies=policies,
        versions=versions,
        audit=audit,
    )


InfluencerServiceDep = Annotated[InfluencerService, Depends(get_influencer_service)]


def get_version_service(
    influencers: Annotated[InfluencerRepository, Depends(get_influencer_repository)],
    versions: Annotated[InfluencerVersionRepository, Depends(get_version_repository)],
    audit: AuditServiceDep,
) -> InfluencerVersionService:
    return InfluencerVersionService(
        influencers=influencers,
        versions=versions,
        audit=audit,
    )


VersionServiceDep = Annotated[InfluencerVersionService, Depends(get_version_service)]


# --- Identity ---------------------------------------------------------------


async def get_current_actor(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)],
    settings: SettingsDep,
    users: Annotated[UserRepository, Depends(get_user_repository)],
    memberships: Annotated[MembershipRepository, Depends(get_membership_repository)],
    organization_header: Annotated[
        uuid.UUID | None,
        Header(alias=ORGANIZATION_HEADER, description="Organization to act in"),
    ] = None,
) -> CurrentActor:
    """Resolve the caller into a `CurrentActor`.

    The organization is taken from the `X-Organization-Id` header when present,
    otherwise from the token's `org` claim, otherwise from the caller's only
    membership. In every case an active membership must exist — the header is a
    selector, never a grant.
    """
    if credentials is None or not credentials.credentials:
        raise AuthenticationError("Missing bearer token", code="token_missing")

    claims = decode_token(
        settings=settings,
        token=credentials.credentials,
        expected_type=TokenType.ACCESS,
    )
    user = await users.get_by_id(claims.subject)
    if user is None or not user.can_authenticate:
        raise AuthenticationError("Account is not active", code="account_inactive")

    requested_organization = organization_header or claims.organization_id
    if requested_organization is not None:
        membership = await memberships.get_active(
            user_id=user.id,
            organization_id=requested_organization,
        )
        if membership is None:
            raise PermissionDeniedError(
                "You are not a member of that organization",
                code="not_a_member",
                details={"organization_id": str(requested_organization)},
            )
    else:
        active = await memberships.list_active_for_user(user.id)
        if not active:
            raise PermissionDeniedError(
                "User has no active organization membership",
                code="no_membership",
            )
        if len(active) > 1:
            raise PermissionDeniedError(
                f"Specify {ORGANIZATION_HEADER}: this user belongs to several organizations",
                code="organization_required",
            )
        membership = active[0]

    actor = CurrentActor.for_membership(
        organization_id=membership.organization_id,
        user_id=user.id,
        role=membership.role,
        email=user.email,
        display_name=user.display_name,
    )
    # Bind for the logging processor. The context var is request-scoped, so this
    # does not leak between concurrent requests.
    set_actor(actor.to_context())
    return actor


ActorDep = Annotated[CurrentActor, Depends(get_current_actor)]


class RequirePermission:
    """Route dependency asserting one permission.

    Declaring it on the route makes the requirement visible in the generated
    OpenAPI document and fails the request before the handler body runs. The
    services assert the same permission again, so this is a fast guard rather than
    the only guard.
    """

    def __init__(self, permission: Permission) -> None:
        self._permission = permission

    async def __call__(self, actor: ActorDep) -> CurrentActor:
        actor.require_permission(self._permission)
        return actor
