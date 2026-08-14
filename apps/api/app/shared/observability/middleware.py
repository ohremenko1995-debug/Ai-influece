"""Request correlation middleware."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.core.context import get_request_id, new_request_id, reset_request_id, set_request_id
from app.shared.observability.logging import get_logger

if TYPE_CHECKING:  # pragma: no cover - typing only
    from starlette.types import ASGIApp

REQUEST_ID_HEADER = "X-Request-ID"

_logger = get_logger(__name__)


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Assigns a request id, echoes it back, and logs one line per request.

    An inbound `X-Request-ID` is trusted only for correlation, never for
    authorization, and is length-capped so a hostile header cannot bloat log
    lines or audit rows.
    """

    max_inbound_id_length = 128

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        inbound = request.headers.get(REQUEST_ID_HEADER)
        request_id = (
            inbound if inbound and len(inbound) <= self.max_inbound_id_length else new_request_id()
        )
        token = set_request_id(request_id)
        # Also stored on the request: the context var is reset in `finally`, which
        # runs before Starlette's server-error middleware invokes the 500 handler,
        # so a crash would otherwise produce an error envelope with no request id —
        # exactly the case where correlation matters most.
        request.state.request_id = request_id
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            duration_ms = (time.perf_counter() - started) * 1000
            _logger.exception(
                "request_failed",
                method=request.method,
                path=request.url.path,
                duration_ms=round(duration_ms, 2),
            )
            raise
        else:
            duration_ms = (time.perf_counter() - started) * 1000
            response.headers[REQUEST_ID_HEADER] = request_id
            _logger.info(
                "request_completed",
                method=request.method,
                path=request.url.path,
                status_code=response.status_code,
                duration_ms=round(duration_ms, 2),
            )
            return response
        finally:
            reset_request_id(token)


def current_request_id() -> str | None:
    """Re-exported for call sites that only need the id."""
    return get_request_id()
