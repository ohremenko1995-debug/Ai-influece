"""AuditLog table.

Append-only: no `updated_at`, no update path, no delete endpoint. Rows are written
in the same transaction as the change they describe, so an audited change either
lands with its audit row or does not land at all
(docs/adr/0007-audit-log-in-transaction.md).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, ForeignKey, Identity, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db.base import Base, OrganizationScopedMixin, UUIDPrimaryKeyMixin
from app.shared.db.types import enum_column, jsonb_column
from app.shared.permissions.roles import ActorType


class AuditLog(UUIDPrimaryKeyMixin, OrganizationScopedMixin, Base):
    """One recorded action."""

    __tablename__ = "audit_logs"
    __table_args__ = (
        # Primary read pattern: an organization's trail, newest first.
        Index("ix_audit_logs_organization_id_sequence", "organization_id", "sequence_number"),
        # Secondary: the history tab on a single entity page.
        Index("ix_audit_logs_entity_type_entity_id", "entity_type", "entity_id"),
    )

    # Total order across the whole log.
    #
    # `created_at` cannot provide it: `now()` returns the *transaction* timestamp
    # in PostgreSQL, so every entry written by one request carries an identical
    # value — and the UUID primary key is random, so it is no tiebreak either.
    # An IDENTITY column is allocated per INSERT and therefore orders entries
    # within a single transaction correctly, which is exactly what a history tab
    # needs ("created, then updated", not an arbitrary shuffle).
    sequence_number: Mapped[int] = mapped_column(
        BigInteger,
        Identity(always=True),
        nullable=False,
        unique=True,
    )

    actor_type: Mapped[ActorType] = enum_column(
        ActorType,
        constraint_name="audit_log_actor_type",
        index=True,
    )
    # Nullable because system actions have no user behind them. ON DELETE is
    # RESTRICT anyway: users are never hard-deleted, so the reference cannot rot.
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    action: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(nullable=False)

    before_data: Mapped[dict[str, Any] | None] = jsonb_column(nullable=True)
    after_data: Mapped[dict[str, Any] | None] = jsonb_column(nullable=True)

    request_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        server_default=func.now(),
        nullable=False,
        index=True,
    )
