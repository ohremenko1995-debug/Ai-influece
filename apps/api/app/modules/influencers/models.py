"""DisclosurePolicy and Influencer tables.

`DisclosurePolicy` is not in the supplied domain model, but `Influencer` carries a
`disclosure_policy_id`, so the entity is defined here. It encodes the two
disclosures the platform must be able to prove it required: that the character is
AI-generated, and that a given piece of content is advertising.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.shared.db.base import Base, OrganizationScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.shared.db.types import enum_column

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.modules.character_versions.models import InfluencerVersion


class InfluencerStatus(enum.StrEnum):
    """Lifecycle of a virtual character."""

    DRAFT = "draft"
    ACTIVE = "active"
    PAUSED = "paused"
    ARCHIVED = "archived"


class ContentPillar(enum.StrEnum):
    """Strategic purpose of a piece of content."""

    REACH = "reach"
    TRUST = "trust"
    CONVERSION = "conversion"


class DisclosurePolicy(UUIDPrimaryKeyMixin, OrganizationScopedMixin, TimestampMixin, Base):
    """Rules for declaring synthetic and commercial content.

    Held mutable-with-audit rather than versioned: the platform rule allows "an
    immutable version *or* an audit-log entry", and every field change here emits
    `disclosure_policy.updated` carrying before/after data. Content that has been
    approved snapshots the disclosure text it was approved with, so editing a
    policy cannot retroactively change what a reviewer signed off
    (docs/adr/0003-human-approval-gate.md).
    """

    __tablename__ = "disclosure_policies"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "code",
            name="uq_disclosure_policies_organization_id_code",
        ),
    )

    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)

    # AI-content disclosure: is the character's synthetic nature declared, and how.
    ai_disclosure_required: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    ai_disclosure_text: Mapped[str] = mapped_column(Text, nullable=False)

    # Advertising disclosure: applied when a brief is marked as advertising.
    advertising_disclosure_required: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    advertising_disclosure_text: Mapped[str] = mapped_column(Text, nullable=False)

    # When true, content classified high-risk needs a compliance decision rather
    # than an ordinary reviewer decision.
    requires_high_risk_approval: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    is_default: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class Influencer(UUIDPrimaryKeyMixin, OrganizationScopedMixin, TimestampMixin, Base):
    """A virtual character.

    Two compliance flags gate activation, checked by
    `app.modules.influencers.service.InfluencerService`:

    * `adult_representation_confirmed` — an explicit record that the character
      depicts an adult. Never defaulted to true.
    * `disclosure_policy_id` — a character cannot go live without a policy saying
      how its AI nature is disclosed.

    Never hard-deleted. `archived_at` is the soft-delete marker and `status` moves
    to `archived`; rows stay readable so lineage and audit history survive.
    """

    __tablename__ = "influencers"
    __table_args__ = (
        UniqueConstraint("organization_id", "code", name="uq_influencers_organization_id_code"),
    )

    code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    public_name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[InfluencerStatus] = enum_column(
        InfluencerStatus,
        constraint_name="influencer_status",
        default=InfluencerStatus.DRAFT,
        index=True,
    )
    niche: Mapped[str | None] = mapped_column(String(200), nullable=True)
    primary_language: Mapped[str] = mapped_column(String(16), nullable=False)
    primary_market: Mapped[str] = mapped_column(String(16), nullable=False)

    adult_representation_confirmed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    disclosure_policy_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("disclosure_policies.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    archived_at: Mapped[datetime | None] = mapped_column(nullable=True)

    disclosure_policy: Mapped[DisclosurePolicy | None] = relationship(lazy="joined")
    versions: Mapped[list[InfluencerVersion]] = relationship(
        back_populates="influencer",
        lazy="raise",
        order_by="InfluencerVersion.version_number",
    )

    @property
    def is_archived(self) -> bool:
        return self.archived_at is not None
