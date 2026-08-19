"""structlog configuration.

Console renderer locally, JSON in every other environment. The request id and the
acting identity are injected by a processor rather than passed to each call site,
so a log line can always be tied back to a request and an actor.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog
from structlog.types import EventDict, Processor, WrappedLogger

from app.core.config import Settings
from app.core.context import get_actor, get_request_id


def _add_request_context(
    _logger: WrappedLogger,
    _method_name: str,
    event_dict: EventDict,
) -> EventDict:
    """Attach the ambient request id and actor, when there is one."""
    request_id = get_request_id()
    if request_id is not None:
        event_dict.setdefault("request_id", request_id)

    actor = get_actor()
    if actor is not None:
        event_dict.setdefault("actor_type", actor.actor_type)
        if actor.actor_id is not None:
            event_dict.setdefault("actor_id", str(actor.actor_id))
        if actor.organization_id is not None:
            event_dict.setdefault("organization_id", str(actor.organization_id))
        if actor.role is not None:
            event_dict.setdefault("role", actor.role)
    return event_dict


def configure_logging(settings: Settings) -> None:
    """Configure structlog and route the standard library through it."""
    shared_processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        # NOT `structlog.stdlib.add_logger_name`: it reads `logger.name`, which
        # only exists on stdlib-backed loggers. `get_logger` binds the name
        # explicitly instead.
        _add_request_context,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
    ]

    renderer: Processor
    if settings.log_format == "console":
        renderer = structlog.dev.ConsoleRenderer(
            colors=sys.stderr.isatty(),
            # Plain tracebacks, not structlog's default rich renderer. Rich
            # pretty-prints every frame's local variables, which for a failed
            # request means serialising the ASGI scope, the SQLAlchemy session and
            # the ORM objects it holds — measured at well over a minute of CPU for
            # a single unhandled exception. A service cannot pay that to log an
            # error.
            exception_formatter=structlog.dev.plain_traceback,
        )
    else:
        shared_processors.append(structlog.processors.format_exc_info)
        renderer = structlog.processors.JSONRenderer()

    structlog.configure(
        processors=[*shared_processors, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelNamesMapping()[settings.log_level]
        ),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=True,
    )

    # Keep uvicorn/sqlalchemy output at the same level, in the same stream.
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stderr,
        level=settings.log_level,
        force=True,
    )
    # These libraries install their own handler *and* propagate to the root, so
    # every line they emit is printed twice — once in their format, once in ours.
    # Dropping their handler leaves a single stream in the format LOG_FORMAT asked
    # for. `arq` is in the list because its CLI configures logging before the
    # worker's startup hook runs; in the API process the clear is a no-op.
    for noisy in ("uvicorn.access", "uvicorn.error", "arq"):
        logging.getLogger(noisy).handlers.clear()
        logging.getLogger(noisy).propagate = True


def get_logger(name: str, **initial: Any) -> structlog.stdlib.BoundLogger:
    """A lazy logger that carries its module name as the `logger` field.

    The name and any extras are passed as *initial values* rather than through
    `.bind()`. That distinction matters: `.bind()` materialises the proxy
    immediately, and module-level loggers are created while modules are still
    being imported — before `configure_logging` runs. Such a logger would freeze
    structlog's default processor chain, whose exception formatter is rich's, and
    rich renders every frame's locals. Measured cost of one unhandled request
    exception rendered that way: over four minutes of CPU.
    """
    # `logger_name`, not `logger`: `logger` is the name of `wrap_logger`'s first
    # parameter, so it cannot be used as an initial value. Both renderers treat
    # `logger_name` as the logger's identity.
    logger: structlog.stdlib.BoundLogger = structlog.get_logger(logger_name=name, **initial)
    return logger
