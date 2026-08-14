"""Influencer lifecycle state machine tests.

The transition table is asserted exhaustively — for every (from, to) pair, the
machine either allows it because the table says so, or refuses it. That way a
future edit to the table cannot quietly open a path nobody intended.
"""

from __future__ import annotations

import itertools

import pytest

from app.core.errors import InvalidTransitionError
from app.modules.influencers.models import InfluencerStatus
from app.modules.influencers.state_machine import (
    INFLUENCER_STATE_MACHINE,
    INFLUENCER_TRANSITIONS,
)

ALLOWED_PAIRS = {
    (InfluencerStatus.DRAFT, InfluencerStatus.ACTIVE),
    (InfluencerStatus.DRAFT, InfluencerStatus.ARCHIVED),
    (InfluencerStatus.ACTIVE, InfluencerStatus.PAUSED),
    (InfluencerStatus.ACTIVE, InfluencerStatus.ARCHIVED),
    (InfluencerStatus.PAUSED, InfluencerStatus.ACTIVE),
    (InfluencerStatus.PAUSED, InfluencerStatus.ARCHIVED),
}


@pytest.mark.parametrize(
    ("current", "target"),
    list(itertools.product(InfluencerStatus, InfluencerStatus)),
)
def test_transition_table_is_exhaustive(
    current: InfluencerStatus,
    target: InfluencerStatus,
) -> None:
    expected = (current, target) in ALLOWED_PAIRS
    assert INFLUENCER_STATE_MACHINE.can_transition(current, target) is expected


def test_every_status_has_a_table_entry() -> None:
    assert set(INFLUENCER_TRANSITIONS) == set(InfluencerStatus)


def test_archived_is_terminal() -> None:
    assert INFLUENCER_STATE_MACHINE.is_terminal(InfluencerStatus.ARCHIVED)
    assert INFLUENCER_STATE_MACHINE.allowed_from(InfluencerStatus.ARCHIVED) == frozenset()


@pytest.mark.parametrize("status", list(InfluencerStatus))
def test_no_status_transitions_to_itself(status: InfluencerStatus) -> None:
    assert not INFLUENCER_STATE_MACHINE.can_transition(status, status)


def test_draft_cannot_be_paused() -> None:
    """Pausing something that was never live is meaningless, not merely unusual."""
    with pytest.raises(InvalidTransitionError) as exc_info:
        INFLUENCER_STATE_MACHINE.assert_transition(
            InfluencerStatus.DRAFT,
            InfluencerStatus.PAUSED,
        )
    details = exc_info.value.details
    assert details["current_status"] == "draft"
    assert details["requested_status"] == "paused"
    assert "active" in str(details["reason"])


def test_leaving_a_terminal_state_explains_why() -> None:
    with pytest.raises(InvalidTransitionError) as exc_info:
        INFLUENCER_STATE_MACHINE.assert_transition(
            InfluencerStatus.ARCHIVED,
            InfluencerStatus.ACTIVE,
        )
    assert "terminal" in str(exc_info.value.details["reason"])


def test_repeating_the_current_state_is_reported_as_such() -> None:
    with pytest.raises(InvalidTransitionError) as exc_info:
        INFLUENCER_STATE_MACHINE.assert_transition(
            InfluencerStatus.ACTIVE,
            InfluencerStatus.ACTIVE,
        )
    assert "already in" in str(exc_info.value.details["reason"])


def test_allowed_transition_does_not_raise() -> None:
    INFLUENCER_STATE_MACHINE.assert_transition(InfluencerStatus.DRAFT, InfluencerStatus.ACTIVE)


def test_invalid_transition_maps_to_conflict() -> None:
    """The HTTP layer must report a refused transition as 409, not 500."""
    error = InvalidTransitionError("Influencer", "archived", "active")
    assert error.status_code == 409
    assert error.code == "invalid_transition"
