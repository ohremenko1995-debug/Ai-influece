"""User table."""

from __future__ import annotations

import enum
from typing import TYPE_CHECKING

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.shared.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.shared.db.types import enum_column

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.modules.organizations.models import Membership


class UserStatus(enum.StrEnum):
    """Account lifecycle. Only `ACTIVE` users can authenticate."""

    INVITED = "invited"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    DISABLED = "disabled"


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A human operator of the platform.

    `password_hash` is nullable on purpose: invited users have no credential yet,
    and an SSO-backed account never will. It is not part of the documented domain
    model because it is a credential detail, not a domain attribute — it is never
    serialised into an API response or an audit row.
    """

    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[UserStatus] = enum_column(
        UserStatus,
        constraint_name="user_status",
        default=UserStatus.INVITED,
        index=True,
    )
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)

    memberships: Mapped[list[Membership]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="raise",
    )

    @property
    def can_authenticate(self) -> bool:
        return self.status is UserStatus.ACTIVE
