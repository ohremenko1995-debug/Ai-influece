"""Request-scoped ambient context.

Only two values live here — the request id and the acting identity — because both
are needed by code that has no business taking them as parameters (structlog
processors, the audit writer). Everything else is passed explicitly.
"""

from __future__ import annotations

import uuid
from contextvars import ContextVar, Token
from dataclasses import dataclass

_request_id: ContextVar[str | None] = ContextVar("influenceros_request_id", default=None)
_actor: ContextVar[ActorContext | None] = ContextVar("influenceros_actor", default=None)


@dataclass(frozen=True, slots=True)
class ActorContext:
    """Minimal identity echo for logs and audit rows."""

    actor_type: str
    actor_id: uuid.UUID | None
    organization_id: uuid.UUID | None
    role: str | None


def new_request_id() -> str:
    return str(uuid.uuid4())


def set_request_id(request_id: str) -> Token[str | None]:
    return _request_id.set(request_id)


def get_request_id() -> str | None:
    return _request_id.get()


def set_actor(actor: ActorContext) -> Token[ActorContext | None]:
    return _actor.set(actor)


def get_actor() -> ActorContext | None:
    return _actor.get()


def reset_request_id(token: Token[str | None]) -> None:
    _request_id.reset(token)


def reset_actor(token: Token[ActorContext | None]) -> None:
    _actor.reset(token)
