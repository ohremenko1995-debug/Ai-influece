"""`/api/v1/audit-logs` routes."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import ActorDep, AuditRepositoryDep, RequirePermission
from app.api.schemas import DEFAULT_PAGE_SIZE, LimitQuery, OffsetQuery, Page
from app.modules.audit.schemas import AuditLogDiff, AuditLogRead
from app.modules.audit.serialization import diff
from app.shared.permissions.permissions import Permission
from app.shared.permissions.roles import ActorType

router = APIRouter(prefix="/audit-logs", tags=["audit-logs"])


@router.get(
    "",
    response_model=Page[AuditLogDiff],
    dependencies=[Depends(RequirePermission(Permission.AUDIT_READ))],
    summary="Query the audit trail",
    description=(
        "Append-only. Scoped to the caller's organization; there is no endpoint "
        "that modifies or removes an entry."
    ),
)
async def list_audit_logs(
    actor: ActorDep,
    audit: AuditRepositoryDep,
    entity_type: Annotated[str | None, Query(max_length=100)] = None,
    entity_id: Annotated[uuid.UUID | None, Query()] = None,
    action: Annotated[str | None, Query(max_length=100)] = None,
    actor_id: Annotated[uuid.UUID | None, Query()] = None,
    actor_type: Annotated[ActorType | None, Query()] = None,
    created_from: Annotated[datetime | None, Query()] = None,
    created_to: Annotated[datetime | None, Query()] = None,
    limit: Annotated[LimitQuery, Query()] = DEFAULT_PAGE_SIZE,
    offset: Annotated[OffsetQuery, Query()] = 0,
) -> Page[AuditLogDiff]:
    entries = await audit.list_entries(
        organization_id=actor.organization_id,
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        actor_id=actor_id,
        actor_type=actor_type,
        created_from=created_from,
        created_to=created_to,
        limit=limit,
        offset=offset,
    )
    total = await audit.count_entries(
        organization_id=actor.organization_id,
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        actor_id=actor_id,
        actor_type=actor_type,
        created_from=created_from,
        created_to=created_to,
    )
    return Page[AuditLogDiff](
        items=[
            AuditLogDiff(
                entry=AuditLogRead.model_validate(entry),
                # A creation has no `before_data`; diffing against nothing would
                # report every column as changed, which is noise rather than signal.
                changed_fields=(
                    diff(entry.before_data, entry.after_data)
                    if entry.before_data is not None
                    else {}
                ),
            )
            for entry in entries
        ],
        total=total,
        limit=limit,
        offset=offset,
    )
