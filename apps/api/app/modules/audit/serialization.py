"""Turning ORM rows into JSON-safe audit snapshots."""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import inspect

from app.shared.db.base import Base

REDACTED = "[redacted]"

# Columns whose value must never reach the audit log. The column still appears in
# the snapshot with a placeholder, so a change remains visible without the secret
# being stored.
REDACTED_COLUMNS: frozenset[str] = frozenset({"password_hash"})


def _to_jsonable(value: Any) -> Any:  # noqa: PLR0911 - a type dispatch reads best as early returns
    """Convert a Python value into something `json.dumps` accepts."""
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, enum.Enum):
        return value.value
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _to_jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple | set):
        return [_to_jsonable(item) for item in value]
    return str(value)


def snapshot(instance: Base, *, exclude: frozenset[str] = frozenset()) -> dict[str, Any]:
    """A JSON-safe dict of `instance`'s mapped columns.

    Relationships are skipped: an audit row records the entity that changed, not
    its neighbours. Only loaded column values are read, so this never triggers
    lazy IO while a transaction is being finalised.
    """
    mapper = inspect(type(instance)).mapper
    unloaded = inspect(instance).unloaded
    result: dict[str, Any] = {}
    for column in mapper.column_attrs:
        key = column.key
        if key in exclude or key in unloaded:
            continue
        if key in REDACTED_COLUMNS:
            result[key] = REDACTED
            continue
        result[key] = _to_jsonable(getattr(instance, key))
    return result


def diff(
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
) -> dict[str, Any]:
    """The changed keys between two snapshots, as `{key: {"from": x, "to": y}}`."""
    before = before or {}
    after = after or {}
    changed: dict[str, Any] = {}
    for key in sorted(set(before) | set(after)):
        old = before.get(key)
        new = after.get(key)
        if old != new:
            changed[key] = {"from": old, "to": new}
    return changed
