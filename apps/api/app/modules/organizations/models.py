"""Organization and Membership tables."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.shared.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.shared.db.types import enum_column
from app.shared.permissions.roles import Role

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.modules.users.models import User


class Organization(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A tenant. Every production record is scoped to exactly one."""

    __tablename__ = "organizations"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)

    memberships: Mapped[list[Membership]] = relationship(
        back_populates="organization",
        cascade="all, delete-orphan",
        lazy="raise",
    )


class Membership(UUIDPrimaryKeyMixin, Base):
    """Binds a user to an organization with exactly one role.

    A user may hold different roles in different organizations, so authorization
    is always resolved per (user, organization) pair rather than per user.

    Revocation is a soft delete (`revoked_at`): a membership that once granted
    access must remain visible in the audit trail.
    """

    __tablename__ = "memberships"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "user_id",
            name="uq_memberships_organization_id_user_id",
        ),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    role: Mapped[Role] = enum_column(Role, constraint_name="membership_role")
    created_at: Mapped[datetime] = mapped_column(
        server_default=func.now(),
        nullable=False,
        index=True,
    )
    revoked_at: Mapped[datetime | None] = mapped_column(nullable=True)

    organization: Mapped[Organization] = relationship(
        back_populates="memberships",
        lazy="joined",
    )
    user: Mapped[User] = relationship(back_populates="memberships", lazy="joined")

    @property
    def is_active(self) -> bool:
        return self.revoked_at is None
