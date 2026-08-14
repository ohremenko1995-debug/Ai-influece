"""InfluencerVersion table — the Character Bible snapshot.

Append-only. There is no update path anywhere in the codebase: a change to a
character's identity produces version N+1 and moves the `is_current` marker.
That is what makes any historical generation explainable — you can always fetch
the exact identity constraints that were in force when it ran
(docs/adr/0002-versioned-production-assets.md).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.shared.db.base import Base, UUIDPrimaryKeyMixin
from app.shared.db.types import jsonb_column

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.modules.influencers.models import Influencer


class InfluencerVersion(UUIDPrimaryKeyMixin, Base):
    """One immutable revision of an influencer's Character Bible."""

    __tablename__ = "influencer_versions"
    __table_args__ = (
        UniqueConstraint(
            "influencer_id",
            "version_number",
            name="uq_influencer_versions_influencer_id_version_number",
        ),
        CheckConstraint("version_number >= 1", name="version_number_positive"),
        # At most one current version per influencer, enforced by the database
        # rather than by application discipline.
        Index(
            "uq_influencer_versions_influencer_id_current",
            "influencer_id",
            unique=True,
            postgresql_where=text("is_current"),
        ),
    )

    influencer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("influencers.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    change_summary: Mapped[str] = mapped_column(String(500), nullable=False)

    biography: Mapped[str | None] = mapped_column(Text, nullable=True)
    tone_of_voice: Mapped[str | None] = mapped_column(Text, nullable=True)
    personality_traits: Mapped[list[Any]] = jsonb_column(default_factory=list)
    prohibited_topics: Mapped[list[Any]] = jsonb_column(default_factory=list)
    visual_constraints: Mapped[dict[str, Any]] = jsonb_column(default_factory=dict)
    speech_constraints: Mapped[dict[str, Any]] = jsonb_column(default_factory=dict)

    created_by: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        server_default=func.now(),
        nullable=False,
        index=True,
    )
    is_current: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    influencer: Mapped[Influencer] = relationship(back_populates="versions", lazy="raise")
