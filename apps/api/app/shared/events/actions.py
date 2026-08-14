"""The closed set of auditable domain actions.

Naming: `<entity>.<past_tense_verb>`, lowercase, dot-separated. Members are added
as each MVP step lands — the ones below cover authentication, the influencer
registry and character versioning.
"""

from __future__ import annotations

import enum


class DomainAction(enum.StrEnum):
    """Every action that produces an audit-log entry."""

    # --- Authentication -----------------------------------------------------
    AUTH_LOGIN_SUCCEEDED = "auth.login_succeeded"
    AUTH_LOGIN_FAILED = "auth.login_failed"
    AUTH_TOKEN_REFRESHED = "auth.token_refreshed"
    AUTH_DEV_LOGIN_USED = "auth.dev_login_used"

    # --- Organizations & membership ----------------------------------------
    ORGANIZATION_CREATED = "organization.created"
    ORGANIZATION_UPDATED = "organization.updated"
    MEMBERSHIP_CREATED = "membership.created"
    MEMBERSHIP_ROLE_CHANGED = "membership.role_changed"
    MEMBERSHIP_REVOKED = "membership.revoked"

    # --- Disclosure policies ------------------------------------------------
    DISCLOSURE_POLICY_CREATED = "disclosure_policy.created"
    DISCLOSURE_POLICY_UPDATED = "disclosure_policy.updated"

    # --- Influencer registry ------------------------------------------------
    INFLUENCER_CREATED = "influencer.created"
    INFLUENCER_UPDATED = "influencer.updated"
    INFLUENCER_STATUS_CHANGED = "influencer.status_changed"
    INFLUENCER_ARCHIVED = "influencer.archived"

    # --- Character bible ----------------------------------------------------
    INFLUENCER_VERSION_CREATED = "influencer_version.created"
    INFLUENCER_VERSION_PROMOTED = "influencer_version.promoted"
