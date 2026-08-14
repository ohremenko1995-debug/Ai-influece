"""Domain error hierarchy and its HTTP projection.

Domain and service code raises these; a single set of exception handlers in
`app.main` turns them into the API error envelope. Routers never build error
responses by hand, so the wire format cannot drift between endpoints.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import Any


class DomainError(Exception):
    """Base class for every expected, business-meaningful failure.

    Anything that is *not* a `DomainError` is an unexpected fault: it is logged
    with a traceback and reported as 500 with no internal detail leaked.
    """

    status_code: int = HTTPStatus.BAD_REQUEST
    code: str = "domain_error"

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code
        self.details: dict[str, Any] = details or {}


class AuthenticationError(DomainError):
    """Caller could not be identified (missing, malformed or expired token)."""

    status_code = HTTPStatus.UNAUTHORIZED
    code = "authentication_failed"


class PermissionDeniedError(DomainError):
    """Caller is known but lacks the required permission in this organization."""

    status_code = HTTPStatus.FORBIDDEN
    code = "permission_denied"


class NotFoundError(DomainError):
    """Entity does not exist, or is not visible to the caller's organization.

    Cross-organization access is reported as 404 rather than 403 so the API does
    not confirm the existence of another tenant's records.
    """

    status_code = HTTPStatus.NOT_FOUND
    code = "not_found"


class ConflictError(DomainError):
    """Request collides with current state (duplicate key, concurrent update)."""

    status_code = HTTPStatus.CONFLICT
    code = "conflict"


class InvalidTransitionError(ConflictError):
    """A state machine refused the requested transition."""

    code = "invalid_transition"

    def __init__(
        self,
        entity: str,
        current: str,
        requested: str,
        *,
        reason: str | None = None,
    ) -> None:
        detail = f"{entity} cannot move from '{current}' to '{requested}'"
        if reason:
            detail = f"{detail}: {reason}"
        super().__init__(
            detail,
            details={
                "entity": entity,
                "current_status": current,
                "requested_status": requested,
                "reason": reason,
            },
        )


class PolicyViolationError(DomainError):
    """A compliance or disclosure precondition is not satisfied.

    Distinct from a plain validation error: the payload is well-formed, but
    acting on it would breach a documented policy (for example activating an
    influencer whose adult-representation confirmation is missing).
    """

    status_code = HTTPStatus.UNPROCESSABLE_ENTITY
    code = "policy_violation"


class DomainValidationError(DomainError):
    """Semantically invalid input that Pydantic cannot express on its own."""

    status_code = HTTPStatus.UNPROCESSABLE_ENTITY
    code = "validation_error"


class ImmutableEntityError(ConflictError):
    """Attempt to mutate an append-only record (a version snapshot)."""

    code = "immutable_entity"
