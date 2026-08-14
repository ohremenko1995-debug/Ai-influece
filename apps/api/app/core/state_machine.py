"""A small, explicit state machine.

Status rules live in a declared transition table rather than scattered `if`
statements, so the legal moves for an entity can be read in one place — and
exposed to the UI, which is how a client learns which buttons to show without
becoming the enforcement point.

Preconditions that depend on other data (an approval record, a compliance flag)
are *not* modelled here. They stay in the owning domain service, because they need
repository access and produce their own error types.
"""

from __future__ import annotations

import enum
from collections.abc import Mapping
from typing import Final

from app.core.errors import InvalidTransitionError


class StateMachine[StateT: enum.StrEnum]:
    """Declared transitions for one entity's status column."""

    def __init__(
        self,
        *,
        entity_name: str,
        transitions: Mapping[StateT, frozenset[StateT]],
    ) -> None:
        self.entity_name: Final = entity_name
        self._transitions: Final = dict(transitions)

    def allowed_from(self, current: StateT) -> frozenset[StateT]:
        """States reachable from `current` in one step."""
        return self._transitions.get(current, frozenset())

    def is_terminal(self, state: StateT) -> bool:
        """A state with no outgoing transitions. Nothing can leave it, ever."""
        return not self._transitions.get(state)

    def can_transition(self, current: StateT, requested: StateT) -> bool:
        return requested in self.allowed_from(current)

    def assert_transition(
        self,
        current: StateT,
        requested: StateT,
        *,
        reason: str | None = None,
    ) -> None:
        """Raise `InvalidTransitionError` unless the move is declared."""
        if self.can_transition(current, requested):
            return
        explanation = reason
        if explanation is None:
            if current == requested:
                explanation = f"already in '{current.value}'"
            elif self.is_terminal(current):
                explanation = f"'{current.value}' is terminal"
            else:
                allowed = sorted(state.value for state in self.allowed_from(current))
                explanation = f"allowed next states are {allowed}"
        raise InvalidTransitionError(
            self.entity_name,
            current.value,
            requested.value,
            reason=explanation,
        )
