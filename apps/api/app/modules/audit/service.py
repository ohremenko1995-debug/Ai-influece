"""Audit writer.

The only way to create an audit row. It flushes but never commits: the enclosing
unit of work owns the transaction, so the audit row and the change it describes
share a fate (docs/adr/0007-audit-log-in-transaction.md).
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from app.core.actor import CurrentActor
from app.core.context import get_request_id
from app.modules.audit.models import AuditLog
from app.modules.audit.serialization import snapshot
from app.shared.events.actions import DomainAction
from app.shared.observability.logging import get_logger

if TYPE_CHECKING:  # pragma: no cover - typing only
    from typing import Any

    from sqlalchemy.ext.asyncio import AsyncSession

    from app.shared.db.base import Base

_logger = get_logger(__name__)


class AuditService:
    """Records domain actions against the current transaction."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record(
        self,
        *,
        actor: CurrentActor,
        action: DomainAction,
        entity_type: str,
        entity_id: uuid.UUID,
        before_data: dict[str, Any] | None = None,
        after_data: dict[str, Any] | None = None,
        organization_id: uuid.UUID | None = None,
    ) -> AuditLog:
        """Append one audit row."""
        entry = AuditLog(
            organization_id=organization_id or actor.organization_id,
            actor_type=actor.actor_type,
            actor_id=actor.user_id,
            action=action.value,
            entity_type=entity_type,
            entity_id=entity_id,
            before_data=before_data,
            after_data=after_data,
            request_id=get_request_id(),
        )
        self._session.add(entry)
        # Flush so a constraint violation surfaces here rather than at commit,
        # where it would be much harder to attribute.
        await self._session.flush()
        _logger.info(
            "audit_recorded",
            action=action.value,
            entity_type=entity_type,
            entity_id=str(entity_id),
        )
        return entry

    async def record_entity_change(
        self,
        *,
        actor: CurrentActor,
        action: DomainAction,
        entity: Base,
        before: dict[str, Any] | None = None,
    ) -> AuditLog:
        """Record a change using `entity`'s current column values as `after_data`.

        `before` must have been captured *before* the mutation — a snapshot taken
        after the fact would record no change at all.
        """
        entity_id = getattr(entity, "id", None)
        if not isinstance(entity_id, uuid.UUID):
            msg = f"{type(entity).__name__} has no UUID primary key to audit"
            raise TypeError(msg)
        return await self.record(
            actor=actor,
            action=action,
            entity_type=type(entity).__name__,
            entity_id=entity_id,
            before_data=before,
            after_data=snapshot(entity),
        )
