"""Character Bible request/response models."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from pydantic import Field, field_validator

from app.api.schemas import ApiModel, RequestModel

MAX_TRAITS = 30
MAX_PROHIBITED_TOPICS = 100

TraitStr = Annotated[str, Field(min_length=1, max_length=120)]


class InfluencerVersionRead(ApiModel):
    """One immutable Character Bible revision."""

    id: uuid.UUID
    influencer_id: uuid.UUID
    version_number: int
    change_summary: str
    biography: str | None
    tone_of_voice: str | None
    personality_traits: list[Any]
    prohibited_topics: list[Any]
    visual_constraints: dict[str, Any]
    speech_constraints: dict[str, Any]
    created_by: uuid.UUID
    created_at: datetime
    is_current: bool


class InfluencerVersionCreate(RequestModel):
    """A new Character Bible revision.

    Every field is a full value, not a patch: a version is a complete snapshot of
    the identity, so a later reader never has to replay a chain of diffs to know
    what the constraints were.
    """

    change_summary: str = Field(
        min_length=3,
        max_length=500,
        description="Why this revision exists. Shown in the version history.",
    )
    biography: str | None = Field(default=None, max_length=10_000)
    tone_of_voice: str | None = Field(default=None, max_length=4_000)
    personality_traits: list[TraitStr] = Field(default_factory=list, max_length=MAX_TRAITS)
    prohibited_topics: list[TraitStr] = Field(
        default_factory=list,
        max_length=MAX_PROHIBITED_TOPICS,
        description="Topics this character must never speak about",
    )
    visual_constraints: dict[str, Any] = Field(
        default_factory=dict,
        description="Hard visual rules, e.g. {'no_tattoos': true, 'eye_color': 'green'}",
    )
    speech_constraints: dict[str, Any] = Field(
        default_factory=dict,
        description="Speech rules, e.g. {'max_wpm': 165, 'forbidden_phrases': [...]}",
    )

    @field_validator("personality_traits", "prohibited_topics")
    @classmethod
    def _reject_duplicates(cls, value: list[str]) -> list[str]:
        seen = {item.casefold() for item in value}
        if len(seen) != len(value):
            msg = "entries must be unique (case-insensitive)"
            raise ValueError(msg)
        return value
