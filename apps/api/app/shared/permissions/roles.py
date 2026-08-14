"""Roles and actor types.

A role is held per organization through a `Membership`, never globally, so the
same user can be an operator in one organization and a reviewer in another.
"""

from __future__ import annotations

import enum


class Role(enum.StrEnum):
    """Membership roles, ordered loosely from broadest to narrowest authority."""

    OWNER = "owner"
    CREATIVE_LEAD = "creative_lead"
    OPERATOR = "operator"
    REVIEWER = "reviewer"
    COMPLIANCE = "compliance"
    ANALYST = "analyst"
    AGENT = "agent"


class ActorType(enum.StrEnum):
    """Who caused a change. Recorded on every audit row.

    `AGENT` is separated from `USER` so that automated activity stays
    distinguishable in the audit trail forever, not just while the token lives.
    """

    USER = "user"
    SYSTEM = "system"
    AGENT = "agent"
