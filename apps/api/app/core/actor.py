"""The acting identity for one request or one background task.

`CurrentActor` is resolved once, at the edge, and then passed explicitly into every
domain service. Services therefore never inspect the HTTP request, and a worker
can construct a system actor and reuse the same services unchanged.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Self

from app.core.context import ActorContext
from app.core.errors import PermissionDeniedError
from app.shared.permissions.matrix import permissions_for_role
from app.shared.permissions.permissions import Permission
from app.shared.permissions.roles import ActorType, Role


@dataclass(frozen=True, slots=True)
class CurrentActor:
    """Who is acting, in which organization, with which role."""

    organization_id: uuid.UUID
    actor_type: ActorType
    user_id: uuid.UUID | None = None
    role: Role | None = None
    email: str | None = None
    display_name: str | None = None

    @classmethod
    def for_membership(
        cls,
        *,
        organization_id: uuid.UUID,
        user_id: uuid.UUID,
        role: Role,
        email: str,
        display_name: str,
    ) -> Self:
        """Build an actor from a membership.

        The `agent` role is recorded as `actor_type=agent`, not `user`, so automated
        activity stays distinguishable in the audit trail permanently.
        """
        return cls(
            organization_id=organization_id,
            actor_type=ActorType.AGENT if role is Role.AGENT else ActorType.USER,
            user_id=user_id,
            role=role,
            email=email,
            display_name=display_name,
        )

    @classmethod
    def system(cls, organization_id: uuid.UUID) -> Self:
        """An actor for work the platform initiates itself (workers, migrations).

        Holds every permission, because it is not a delegated human identity and
        cannot be reached from an HTTP request — no authentication path produces a
        system actor. Its actions are audited with `actor_type=system`.
        """
        return cls(organization_id=organization_id, actor_type=ActorType.SYSTEM)

    @property
    def permissions(self) -> frozenset[Permission]:
        if self.actor_type is ActorType.SYSTEM:
            return frozenset(Permission)
        if self.role is None:
            return frozenset()
        return permissions_for_role(self.role)

    def has_permission(self, permission: Permission) -> bool:
        return permission in self.permissions

    def require_permission(self, permission: Permission) -> None:
        """Raise `PermissionDeniedError` unless the actor holds `permission`.

        Called by domain services, not only by route dependencies: authorization
        must hold for every caller of a service, including background tasks.
        """
        if not self.has_permission(permission):
            raise PermissionDeniedError(
                f"Role '{self.role or self.actor_type}' may not perform '{permission.value}'",
                details={
                    "required_permission": permission.value,
                    "role": self.role.value if self.role else None,
                },
            )

    def to_context(self) -> ActorContext:
        """Projection used by the logging processor."""
        return ActorContext(
            actor_type=self.actor_type.value,
            actor_id=self.user_id,
            organization_id=self.organization_id,
            role=self.role.value if self.role else None,
        )
