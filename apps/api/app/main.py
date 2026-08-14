"""FastAPI application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from http import HTTPStatus

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import __version__
from app.api.health import router as health_router
from app.api.schemas import ErrorDetail, ErrorResponse
from app.api.v1.router import build_v1_router
from app.core.config import Settings, get_settings
from app.core.context import get_request_id
from app.core.errors import DomainError
from app.shared.db.registry import Base  # noqa: F401 - ensures full metadata is loaded
from app.shared.db.session import build_database
from app.shared.observability.logging import configure_logging, get_logger
from app.shared.observability.middleware import RequestContextMiddleware

_logger = get_logger(__name__)

DESCRIPTION = """
Internal control center for producing and governing AI influencers.

**Transparency.** Characters served by this platform are openly virtual. Every
influencer carries a disclosure policy, and content that requires an AI or
advertising disclosure cannot reach a publication surface without one.

**Traceability.** Identity, recipes, workflows and prompts are versioned rather
than edited in place, and every consequential change writes an audit-log entry in
the same transaction as the change itself.
"""


def _error_response(
    *,
    request: Request | None,
    status_code: int,
    code: str,
    message: str,
    details: dict[str, object] | None = None,
) -> JSONResponse:
    # `request.state` first, context var second: the 500 handler runs after the
    # request-context middleware has already reset its context var.
    request_id = getattr(request.state, "request_id", None) if request else None
    payload = ErrorResponse(
        error=ErrorDetail(
            code=code,
            message=message,
            details=details or {},
            request_id=request_id or get_request_id(),
        )
    )
    return JSONResponse(status_code=status_code, content=payload.model_dump(mode="json"))


def register_exception_handlers(app: FastAPI) -> None:
    """One error envelope for the whole API."""

    @app.exception_handler(DomainError)
    async def handle_domain_error(request: Request, exc: DomainError) -> JSONResponse:
        # Expected failures: logged at info, no traceback.
        _logger.info(
            "domain_error",
            code=exc.code,
            status_code=exc.status_code,
            message=exc.message,
        )
        return _error_response(
            request=request,
            status_code=exc.status_code,
            code=exc.code,
            message=exc.message,
            details=exc.details,
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        # Only three keys are copied out, on purpose. A raw pydantic error also
        # carries `ctx` (which holds the live ValueError object for custom field
        # validators — not JSON-serialisable), `input` (the rejected value, which
        # may be a credential) and `url` (a link to pydantic's docs). None of
        # those belong in an API response.
        errors = [
            {
                "location": [str(part) for part in error.get("loc", ())],
                "message": str(error.get("msg", "")),
                "type": str(error.get("type", "")),
            }
            for error in exc.errors()
        ]
        return _error_response(
            request=request,
            status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
            code="request_validation_error",
            message="Request payload is invalid",
            details={"errors": errors},
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(
        request: Request,
        exc: StarletteHTTPException,
    ) -> JSONResponse:
        status = HTTPStatus(exc.status_code)
        return _error_response(
            request=request,
            status_code=exc.status_code,
            code=status.phrase.lower().replace(" ", "_"),
            message=str(exc.detail),
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        # Unexpected fault: full traceback to the log, nothing internal to the client.
        _logger.exception("unhandled_error", error_type=type(exc).__name__)
        return _error_response(
            request=request,
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            code="internal_error",
            message="An unexpected error occurred",
        )


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the ASGI application."""
    resolved = settings or get_settings()
    configure_logging(resolved)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.database = build_database(resolved)
        _logger.info(
            "api_started",
            environment=resolved.environment.value,
            dev_auth_active=resolved.dev_auth_active,
            generation_provider=resolved.generation_provider.value,
        )
        try:
            yield
        finally:
            await app.state.database.dispose()
            _logger.info("api_stopped")

    app = FastAPI(
        title="InfluencerOS API",
        version=__version__,
        description=DESCRIPTION,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url=None,
        openapi_url="/openapi.json",
        responses={
            400: {"model": ErrorResponse, "description": "Domain error"},
            401: {"model": ErrorResponse, "description": "Not authenticated"},
            403: {"model": ErrorResponse, "description": "Permission denied"},
            404: {"model": ErrorResponse, "description": "Not found"},
            409: {"model": ErrorResponse, "description": "Conflict"},
            422: {"model": ErrorResponse, "description": "Validation or policy failure"},
        },
    )

    # Set outside the lifespan so `get_app_settings` works even when the app is
    # driven directly by an ASGI transport (tests, in-process tooling).
    app.state.settings = resolved

    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=resolved.cors_origin_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Organization-Id", "X-Request-ID"],
        expose_headers=["X-Request-ID"],
    )

    register_exception_handlers(app)
    app.include_router(health_router)
    app.include_router(build_v1_router(resolved))
    return app


app = create_app()
