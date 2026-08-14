"""Declarative base and the mixins shared by every table.

The explicit naming convention matters: without it Alembic autogenerate produces
migrations that cannot drop unnamed constraints, which turns every later schema
change into hand-written SQL.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, MetaData, Uuid, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

if TYPE_CHECKING:  # pragma: no cover - typing only
    pass

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Root of the ORM hierarchy.

    `type_annotation_map` only covers the unambiguous scalars. JSON and
    enumerated columns are declared explicitly via `jsonb_column` / `enum_column`
    so the storage type of a column is always visible at its definition.
    """

    metadata = MetaData(naming_convention=NAMING_CONVENTION)

    type_annotation_map = {  # noqa: RUF012 - SQLAlchemy reads this as a plain dict
        uuid.UUID: Uuid(as_uuid=True),
        datetime: DateTime(timezone=True),
    }

    def __repr__(self) -> str:
        identifier = getattr(self, "id", None)
        return f"<{type(self).__name__} id={identifier}>"


class UUIDPrimaryKeyMixin:
    """Random UUID primary key.

    UUIDv4 (not v7) because the standard library has no v7 generator on 3.12.
    Chronological ordering therefore always goes through `created_at`, never
    through the key — see docs/adr/0002-versioned-production-assets.md.
    """

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)


class TimestampMixin:
    """`created_at` / `updated_at`, both timezone-aware and set by the database.

    `eager_defaults=True` is required, not cosmetic. `onupdate=func.now()` is a SQL
    expression, so after an UPDATE SQLAlchemy would mark `updated_at` expired and
    reload it on next access — a lazy, synchronous read that raises
    `MissingGreenlet` when a Pydantic response model touches the attribute. With
    eager defaults the value comes back via RETURNING in the same statement.
    """

    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012 - SQLAlchemy reads a plain dict

    created_at: Mapped[datetime] = mapped_column(
        server_default=func.now(),
        nullable=False,
        index=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class OrganizationScopedMixin:
    """Tenant key.

    Every scoped repository filters on this column; a missing filter is a
    cross-tenant leak, so the FK is indexed and never nullable.
    """

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
