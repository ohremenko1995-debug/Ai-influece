"""Audit log response models."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import Field

from app.api.schemas import ApiModel
from app.shared.permissions.roles import ActorType


class AuditLogRead(ApiModel):
    """One audit entry."""

    id: uuid.UUID
    sequence_number: int = Field(description="Monotonic total order across the log")
    organization_id: uuid.UUID
    actor_type: ActorType
    actor_id: uuid.UUID | None
    action: str
    entity_type: str
    entity_id: uuid.UUID
    before_data: dict[str, Any] | None = None
    after_data: dict[str, Any] | None = None
    request_id: str | None = None
    created_at: datetime


class AuditLogDiff(ApiModel):
    """An entry plus the computed field-level diff, for the history tab."""

    entry: AuditLogRead
    changed_fields: dict[str, Any] = Field(
        default_factory=dict,
        description='Changed keys as {"field": {"from": old, "to": new}}',
    )
