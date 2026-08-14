"""Audit log reads."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import ColumnElement, func, select

from app.modules.audit.models import AuditLog
from app.shared.permissions.roles import ActorType

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Sequence

    from sqlalchemy.ext.asyncio import AsyncSession


class AuditRepository:
    """Read-only access to the audit trail.

    There is deliberately no create/update/delete here — writes go through
    `AuditService`, so there is a single place that stamps actor and request id.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_entries(
        self,
        *,
        organization_id: uuid.UUID,
        entity_type: str | None = None,
        entity_id: uuid.UUID | None = None,
        action: str | None = None,
        actor_id: uuid.UUID | None = None,
        actor_type: ActorType | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Sequence[AuditLog]:
        conditions = self._conditions(
            organization_id=organization_id,
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            actor_id=actor_id,
            actor_type=actor_type,
            created_from=created_from,
            created_to=created_to,
        )
        # Ordered by `sequence_number`, not `created_at`: entries written in one
        # transaction share a `created_at` (PostgreSQL `now()` is the transaction
        # timestamp), so only the sequence gives a stable, meaningful order.
        query = (
            select(AuditLog)
            .where(*conditions)
            .order_by(AuditLog.sequence_number.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self._session.execute(query)
        return result.scalars().all()

    async def count_entries(
        self,
        *,
        organization_id: uuid.UUID,
        entity_type: str | None = None,
        entity_id: uuid.UUID | None = None,
        action: str | None = None,
        actor_id: uuid.UUID | None = None,
        actor_type: ActorType | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
    ) -> int:
        conditions = self._conditions(
            organization_id=organization_id,
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            actor_id=actor_id,
            actor_type=actor_type,
            created_from=created_from,
            created_to=created_to,
        )
        result = await self._session.execute(
            select(func.count()).select_from(AuditLog).where(*conditions)
        )
        return int(result.scalar_one())

    @staticmethod
    def _conditions(
        *,
        organization_id: uuid.UUID,
        entity_type: str | None,
        entity_id: uuid.UUID | None,
        action: str | None,
        actor_id: uuid.UUID | None,
        actor_type: ActorType | None,
        created_from: datetime | None,
        created_to: datetime | None,
    ) -> list[ColumnElement[bool]]:
        """Filter predicates shared by the list and count queries.

        Returned as expressions rather than applied to a query, so the two call
        sites cannot drift — a filter added here affects both the page and its
        total.
        """
        conditions: list[ColumnElement[bool]] = [AuditLog.organization_id == organization_id]
        if entity_type is not None:
            conditions.append(AuditLog.entity_type == entity_type)
        if entity_id is not None:
            conditions.append(AuditLog.entity_id == entity_id)
        if action is not None:
            conditions.append(AuditLog.action == action)
        if actor_id is not None:
            conditions.append(AuditLog.actor_id == actor_id)
        if actor_type is not None:
            conditions.append(AuditLog.actor_type == actor_type)
        if created_from is not None:
            conditions.append(AuditLog.created_at >= created_from)
        if created_to is not None:
            conditions.append(AuditLog.created_at <= created_to)
        return conditions
