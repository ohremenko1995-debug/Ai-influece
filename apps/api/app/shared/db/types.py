"""Column helpers for the two storage types that need a deliberate choice."""

from __future__ import annotations

import enum
from typing import Any

from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import mapped_column
from sqlalchemy.orm.properties import MappedColumn


def enum_column[EnumT: enum.Enum](
    enum_cls: type[EnumT],
    *,
    constraint_name: str,
    default: EnumT | None = None,
    nullable: bool = False,
    index: bool = False,
) -> MappedColumn[Any]:
    """A status column stored as VARCHAR with a CHECK constraint.

    Native PostgreSQL enums are avoided on purpose: adding a value requires
    `ALTER TYPE ... ADD VALUE`, which cannot run inside a transaction on older
    servers and cannot be reversed at all. A checked VARCHAR is a plain
    `ALTER TABLE` in both directions.
    See docs/adr/0001-modular-monolith.md ("Enumerations").
    """
    return mapped_column(
        SAEnum(
            enum_cls,
            name=constraint_name,
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            values_callable=lambda members: [member.value for member in members],
            length=64,
        ),
        nullable=nullable,
        index=index,
        default=default,
    )


def jsonb_column(
    *,
    nullable: bool = False,
    default_factory: Any = None,
) -> MappedColumn[Any]:
    """A JSONB column.

    JSONB rather than JSON so the contents stay queryable and indexable; several
    of these (`findings`, `guardrail_metrics`) are filtered on later.
    """
    return mapped_column(
        JSONB,
        nullable=nullable,
        default=default_factory,
    )
