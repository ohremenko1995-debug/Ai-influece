"""Organization and membership domain service."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from slugify import slugify

from app.core.actor import CurrentActor
from app.core.errors import ConflictError, DomainValidationError, NotFoundError
from app.modules.audit.serialization import snapshot
from app.modules.audit.service import AuditService
from app.modules.organizations.models import Membership, Organization
from app.modules.organizations.repository import MembershipRepository, OrganizationRepository
from app.shared.events.actions import DomainAction
from app.shared.permissions.permissions import Permission
from app.shared.permissions.roles import Role

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Sequence


class OrganizationService:
    """Creates organizations and manages who belongs to them."""

    def __init__(
        self,
        *,
        organizations: OrganizationRepository,
        memberships: MembershipRepository,
        audit: AuditService,
    ) -> None:
        self._organizations = organizations
        self._memberships = memberships
        self._audit = audit

    async def get(self, *, actor: CurrentActor, organization_id: uuid.UUID) -> Organization:
        actor.require_permission(Permission.ORG_READ)
        if organization_id != actor.organization_id:
            # Do not confirm the existence of another tenant's organization.
            raise NotFoundError("Organization not found")
        organization = await self._organizations.get_by_id(organization_id)
        if organization is None:
            raise NotFoundError("Organization not found")
        return organization

    async def update(
        self,
        *,
        actor: CurrentActor,
        organization_id: uuid.UUID,
        name: str | None,
    ) -> Organization:
        actor.require_permission(Permission.ORG_UPDATE)
        organization = await self.get(actor=actor, organization_id=organization_id)
        if name is None:
            return organization

        before = snapshot(organization)
        organization.name = name
        await self._audit.record_entity_change(
            actor=actor,
            action=DomainAction.ORGANIZATION_UPDATED,
            entity=organization,
            before=before,
        )
        return organization

    async def create_with_owner(
        self,
        *,
        name: str,
        slug: str | None,
        owner_user_id: uuid.UUID,
    ) -> tuple[Organization, Membership]:
        """Create an organization and its first `owner` membership.

        Not permission-guarded on an actor, because it is the bootstrap path: the
        caller has no organization yet, so there is no membership to check against.
        Reachable only from the seed CLI and from tests, never from a router.
        Audited as a system action.
        """
        resolved_slug = slug or slugify(name)
        if not resolved_slug:
            raise DomainValidationError("Organization name must contain slug-able characters")
        if await self._organizations.get_by_slug(resolved_slug) is not None:
            raise ConflictError(
                f"Organization slug '{resolved_slug}' is already taken",
                details={"slug": resolved_slug},
            )

        organization = await self._organizations.create(name=name, slug=resolved_slug)
        actor = CurrentActor.system(organization.id)
        await self._audit.record_entity_change(
            actor=actor,
            action=DomainAction.ORGANIZATION_CREATED,
            entity=organization,
        )

        membership = await self._memberships.create(
            organization_id=organization.id,
            user_id=owner_user_id,
            role=Role.OWNER,
        )
        await self._audit.record_entity_change(
            actor=actor,
            action=DomainAction.MEMBERSHIP_CREATED,
            entity=membership,
        )
        return organization, membership

    async def list_members(self, *, actor: CurrentActor) -> Sequence[Membership]:
        actor.require_permission(Permission.ORG_READ)
        return await self._memberships.list_for_organization(actor.organization_id)

    async def add_member(
        self,
        *,
        actor: CurrentActor,
        user_id: uuid.UUID,
        role: Role,
    ) -> Membership:
        actor.require_permission(Permission.ORG_MEMBER_MANAGE)
        existing = await self._memberships.get_active(
            user_id=user_id,
            organization_id=actor.organization_id,
        )
        if existing is not None:
            raise ConflictError(
                "User is already a member of this organization",
                details={"user_id": str(user_id), "role": existing.role.value},
            )
        membership = await self._memberships.create(
            organization_id=actor.organization_id,
            user_id=user_id,
            role=role,
        )
        await self._audit.record_entity_change(
            actor=actor,
            action=DomainAction.MEMBERSHIP_CREATED,
            entity=membership,
        )
        return membership

    async def change_member_role(
        self,
        *,
        actor: CurrentActor,
        user_id: uuid.UUID,
        role: Role,
    ) -> Membership:
        actor.require_permission(Permission.ORG_MEMBER_MANAGE)
        membership = await self._require_membership(actor, user_id)
        if membership.role is role:
            return membership

        before = snapshot(membership)
        membership.role = role
        await self._audit.record_entity_change(
            actor=actor,
            action=DomainAction.MEMBERSHIP_ROLE_CHANGED,
            entity=membership,
            before=before,
        )
        return membership

    async def revoke_member(self, *, actor: CurrentActor, user_id: uuid.UUID) -> Membership:
        """Soft-revoke a membership.

        A membership is never hard-deleted: the row is what explains who had
        access when a historical action was taken.
        """
        actor.require_permission(Permission.ORG_MEMBER_MANAGE)
        membership = await self._require_membership(actor, user_id)
        if membership.user_id == actor.user_id:
            raise ConflictError(
                "You cannot revoke your own membership",
                code="cannot_revoke_self",
            )

        before = snapshot(membership)
        membership.revoked_at = datetime.now(UTC)
        await self._audit.record_entity_change(
            actor=actor,
            action=DomainAction.MEMBERSHIP_REVOKED,
            entity=membership,
            before=before,
        )
        return membership

    async def _require_membership(self, actor: CurrentActor, user_id: uuid.UUID) -> Membership:
        """The target user's live membership in the actor's organization."""
        membership = await self._memberships.get_active(
            user_id=user_id,
            organization_id=actor.organization_id,
        )
        if membership is None:
            raise NotFoundError("Membership not found")
        return membership
