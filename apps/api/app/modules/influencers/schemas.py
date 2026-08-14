"""Influencer and disclosure-policy request/response models."""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Annotated

from pydantic import Field, field_validator

from app.api.schemas import ApiModel, RequestModel
from app.modules.influencers.models import InfluencerStatus

CODE_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{1,62}[a-z0-9]$")
LANGUAGE_PATTERN = re.compile(r"^[a-z]{2}(?:-[A-Z]{2})?$")
MARKET_PATTERN = re.compile(r"^[A-Z]{2}$")

CodeStr = Annotated[str, Field(min_length=3, max_length=64)]
LanguageStr = Annotated[str, Field(min_length=2, max_length=16)]
MarketStr = Annotated[str, Field(min_length=2, max_length=2)]


# --- Disclosure policy -------------------------------------------------------


class DisclosurePolicyRead(ApiModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    code: str
    name: str
    ai_disclosure_required: bool
    ai_disclosure_text: str
    advertising_disclosure_required: bool
    advertising_disclosure_text: str
    requires_high_risk_approval: bool
    is_default: bool
    notes: str | None
    created_at: datetime
    updated_at: datetime


class DisclosurePolicyCreate(RequestModel):
    code: CodeStr
    name: str = Field(min_length=2, max_length=200)
    ai_disclosure_text: str = Field(
        min_length=3,
        max_length=2000,
        description="Text that declares the character is AI-generated",
    )
    advertising_disclosure_text: str = Field(
        min_length=3,
        max_length=2000,
        description="Text applied when a brief is marked as advertising",
    )
    ai_disclosure_required: bool = True
    advertising_disclosure_required: bool = True
    requires_high_risk_approval: bool = True
    is_default: bool = False
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("code")
    @classmethod
    def _validate_code(cls, value: str) -> str:
        if not CODE_PATTERN.fullmatch(value):
            msg = "code must be lowercase alphanumeric with '-' or '_' separators"
            raise ValueError(msg)
        return value


class DisclosurePolicyUpdate(RequestModel):
    name: str | None = Field(default=None, min_length=2, max_length=200)
    ai_disclosure_required: bool | None = None
    ai_disclosure_text: str | None = Field(default=None, min_length=3, max_length=2000)
    advertising_disclosure_required: bool | None = None
    advertising_disclosure_text: str | None = Field(default=None, min_length=3, max_length=2000)
    requires_high_risk_approval: bool | None = None
    is_default: bool | None = None
    notes: str | None = Field(default=None, max_length=2000)


# --- Influencer --------------------------------------------------------------


class InfluencerRead(ApiModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    code: str
    public_name: str
    status: InfluencerStatus
    niche: str | None
    primary_language: str
    primary_market: str
    adult_representation_confirmed: bool
    disclosure_policy_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None


class InfluencerDetail(InfluencerRead):
    """Detail view with the resolved policy and current bible version number."""

    disclosure_policy: DisclosurePolicyRead | None = None
    current_version_number: int | None = Field(
        default=None,
        description="Version number of the current Character Bible, if any",
    )
    activation_blockers: list[str] = Field(
        default_factory=list,
        description="Reasons this influencer cannot be activated yet",
    )


class InfluencerCreate(RequestModel):
    code: CodeStr = Field(description="Stable internal identifier, unique per organization")
    public_name: str = Field(min_length=1, max_length=200)
    primary_language: LanguageStr = Field(description="BCP-47-ish tag, e.g. 'en' or 'pt-BR'")
    primary_market: MarketStr = Field(description="ISO 3166-1 alpha-2 country code, e.g. 'DE'")
    niche: str | None = Field(default=None, max_length=200)
    disclosure_policy_id: uuid.UUID | None = None
    adult_representation_confirmed: bool = Field(
        default=False,
        description=(
            "Explicit confirmation that the character depicts an adult. "
            "Required before the influencer can be activated."
        ),
    )

    @field_validator("code")
    @classmethod
    def _validate_code(cls, value: str) -> str:
        if not CODE_PATTERN.fullmatch(value):
            msg = "code must be lowercase alphanumeric with '-' or '_' separators"
            raise ValueError(msg)
        return value

    @field_validator("primary_language")
    @classmethod
    def _validate_language(cls, value: str) -> str:
        if not LANGUAGE_PATTERN.fullmatch(value):
            msg = "primary_language must look like 'en' or 'pt-BR'"
            raise ValueError(msg)
        return value

    @field_validator("primary_market")
    @classmethod
    def _validate_market(cls, value: str) -> str:
        if not MARKET_PATTERN.fullmatch(value):
            msg = "primary_market must be an uppercase ISO 3166-1 alpha-2 code"
            raise ValueError(msg)
        return value


class InfluencerUpdate(RequestModel):
    """Partial update.

    `code` is absent on purpose: it is the stable identifier used in storage keys
    and audit rows, so it is fixed at creation. `status` is absent too — status
    moves through the transition endpoint so the state machine always runs.
    """

    public_name: str | None = Field(default=None, min_length=1, max_length=200)
    niche: str | None = Field(default=None, max_length=200)
    primary_language: LanguageStr | None = None
    primary_market: MarketStr | None = None
    disclosure_policy_id: uuid.UUID | None = None
    adult_representation_confirmed: bool | None = None

    @field_validator("primary_language")
    @classmethod
    def _validate_language(cls, value: str | None) -> str | None:
        if value is not None and not LANGUAGE_PATTERN.fullmatch(value):
            msg = "primary_language must look like 'en' or 'pt-BR'"
            raise ValueError(msg)
        return value

    @field_validator("primary_market")
    @classmethod
    def _validate_market(cls, value: str | None) -> str | None:
        if value is not None and not MARKET_PATTERN.fullmatch(value):
            msg = "primary_market must be an uppercase ISO 3166-1 alpha-2 code"
            raise ValueError(msg)
        return value


class InfluencerStatusChange(RequestModel):
    """Requested status transition, validated by the domain state machine."""

    status: InfluencerStatus
    reason: str | None = Field(
        default=None,
        max_length=500,
        description="Recorded in the audit entry for this transition",
    )
