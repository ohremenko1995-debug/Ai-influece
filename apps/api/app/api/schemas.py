"""Envelopes shared by every endpoint."""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field

MAX_PAGE_SIZE = 200
DEFAULT_PAGE_SIZE = 50

LimitQuery = Annotated[int, Field(ge=1, le=MAX_PAGE_SIZE)]
OffsetQuery = Annotated[int, Field(ge=0)]


class ApiModel(BaseModel):
    """Base for every response model.

    `from_attributes` lets a response be built directly from an ORM row;
    `extra="forbid"` on request models is set individually so unknown request
    fields are rejected rather than silently dropped.
    """

    model_config = ConfigDict(from_attributes=True)


class RequestModel(BaseModel):
    """Base for every request body. Unknown fields are an error."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Page[ItemT](BaseModel):
    """One page of results plus the totals needed to render a pager."""

    items: list[ItemT]
    total: int = Field(ge=0, description="Total rows matching the filters, ignoring paging")
    limit: int = Field(ge=1)
    offset: int = Field(ge=0)


class ErrorDetail(BaseModel):
    """The body of every non-2xx response."""

    code: str = Field(description="Stable machine-readable error code")
    message: str = Field(description="Human-readable description; safe to display")
    details: dict[str, Any] = Field(default_factory=dict)
    request_id: str | None = Field(default=None, description="Correlates with server logs")


class ErrorResponse(BaseModel):
    """Error envelope: `{"error": {...}}`."""

    error: ErrorDetail
