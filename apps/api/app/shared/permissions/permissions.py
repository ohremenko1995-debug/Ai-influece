"""The permission vocabulary.

Permissions are fine-grained verbs on bounded-context nouns. Endpoints depend on
permissions, never on roles — so re-shaping a role is a change to
`app.shared.permissions.matrix` alone and cannot silently widen an endpoint.
"""

from __future__ import annotations

import enum


class Permission(enum.StrEnum):
    """Every checkable capability in the system."""

    # --- Organization & membership -----------------------------------------
    ORG_READ = "org:read"
    ORG_UPDATE = "org:update"
    ORG_MEMBER_MANAGE = "org:member_manage"

    # --- Influencer registry ------------------------------------------------
    INFLUENCER_READ = "influencer:read"
    INFLUENCER_CREATE = "influencer:create"
    INFLUENCER_UPDATE = "influencer:update"
    INFLUENCER_ARCHIVE = "influencer:archive"
    INFLUENCER_VERSION_CREATE = "influencer:version_create"

    # --- Disclosure / compliance policies -----------------------------------
    POLICY_READ = "policy:read"
    POLICY_UPDATE = "policy:update"

    # --- Asset library ------------------------------------------------------
    ASSET_READ = "asset:read"
    ASSET_UPLOAD = "asset:upload"
    ASSET_UPDATE = "asset:update"
    ASSET_ARCHIVE = "asset:archive"
    ASSET_MARK_GOLDEN = "asset:mark_golden"

    # --- Voice --------------------------------------------------------------
    VOICE_READ = "voice:read"
    VOICE_MANAGE = "voice:manage"

    # --- Recipes & workflow versions ----------------------------------------
    RECIPE_READ = "recipe:read"
    RECIPE_CREATE = "recipe:create"
    RECIPE_UPDATE = "recipe:update"
    RECIPE_VERSION_CREATE = "recipe:version_create"

    # --- Content factory ----------------------------------------------------
    CONTENT_READ = "content:read"
    CONTENT_CREATE = "content:create"
    CONTENT_UPDATE = "content:update"
    CONTENT_SCRIPT_CREATE = "content:script_create"
    CONTENT_TRANSITION = "content:transition"

    # --- Generation jobs ----------------------------------------------------
    JOB_READ = "job:read"
    JOB_CREATE = "job:create"
    JOB_CANCEL = "job:cancel"

    # --- QA -----------------------------------------------------------------
    QA_READ = "qa:read"
    QA_CREATE = "qa:create"

    # --- Approvals ----------------------------------------------------------
    APPROVAL_READ = "approval:read"
    APPROVAL_REQUEST = "approval:request"
    APPROVAL_DECIDE = "approval:decide"
    APPROVAL_DECIDE_HIGH_RISK = "approval:decide_high_risk"

    # --- Calendar & publication --------------------------------------------
    CALENDAR_READ = "calendar:read"
    CALENDAR_SCHEDULE = "calendar:schedule"
    CALENDAR_PUBLISH_MARK = "calendar:publish_mark"

    # --- Social accounts ----------------------------------------------------
    SOCIAL_ACCOUNT_CONNECT = "social_account:connect"

    # --- Experiments --------------------------------------------------------
    EXPERIMENT_READ = "experiment:read"
    EXPERIMENT_MANAGE = "experiment:manage"

    # --- Observability ------------------------------------------------------
    AUDIT_READ = "audit:read"
    DASHBOARD_READ = "dashboard:read"


READ_PERMISSIONS: frozenset[Permission] = frozenset(
    {
        Permission.ORG_READ,
        Permission.INFLUENCER_READ,
        Permission.POLICY_READ,
        Permission.ASSET_READ,
        Permission.VOICE_READ,
        Permission.RECIPE_READ,
        Permission.CONTENT_READ,
        Permission.JOB_READ,
        Permission.QA_READ,
        Permission.APPROVAL_READ,
        Permission.CALENDAR_READ,
        Permission.EXPERIMENT_READ,
        Permission.DASHBOARD_READ,
    }
)
"""Everything a member may look at. Every role starts from this set."""
