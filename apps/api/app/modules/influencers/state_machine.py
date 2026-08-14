"""Influencer lifecycle transitions.

    draft  -> active | archived
    active -> paused | archived
    paused -> active | archived
    archived -> (terminal)

`archived` is terminal: reviving a retired character would silently reuse an
identity whose audit history says it was retired. A new character gets a new code.
"""

from __future__ import annotations

from app.core.state_machine import StateMachine
from app.modules.influencers.models import InfluencerStatus

INFLUENCER_TRANSITIONS: dict[InfluencerStatus, frozenset[InfluencerStatus]] = {
    InfluencerStatus.DRAFT: frozenset({InfluencerStatus.ACTIVE, InfluencerStatus.ARCHIVED}),
    InfluencerStatus.ACTIVE: frozenset({InfluencerStatus.PAUSED, InfluencerStatus.ARCHIVED}),
    InfluencerStatus.PAUSED: frozenset({InfluencerStatus.ACTIVE, InfluencerStatus.ARCHIVED}),
    InfluencerStatus.ARCHIVED: frozenset(),
}

INFLUENCER_STATE_MACHINE = StateMachine(
    entity_name="Influencer",
    transitions=INFLUENCER_TRANSITIONS,
)
