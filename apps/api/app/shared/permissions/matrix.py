"""The role → permission matrix.

Two design rules, both enforced by tests in `tests/test_rbac_matrix.py`:

1. **Separation of duties.** The role that produces content does not approve it.
   `creative_lead` and `operator` may *request* approval; only `reviewer`,
   `compliance` and `owner` may *decide* one. High-risk content narrows further
   to `compliance` and `owner`.

2. **The agent role is fenced twice.** `AGENT_FORBIDDEN_PERMISSIONS` is subtracted
   from whatever the matrix says, so an editing mistake in the table below cannot
   grant an automated actor the ability to publish, approve, change policy or
   connect a social account.
"""

from __future__ import annotations

from app.shared.permissions.permissions import READ_PERMISSIONS, Permission
from app.shared.permissions.roles import Role

# Permissions an actor with the `agent` role must never hold, whatever the matrix
# below says. Mirrors the platform rule in docs/security.md.
AGENT_FORBIDDEN_PERMISSIONS: frozenset[Permission] = frozenset(
    {
        # publishing / scheduling
        Permission.CALENDAR_SCHEDULE,
        Permission.CALENDAR_PUBLISH_MARK,
        # approvals of any risk level
        Permission.APPROVAL_DECIDE,
        Permission.APPROVAL_DECIDE_HIGH_RISK,
        # policy modification
        Permission.POLICY_UPDATE,
        # social account connection
        Permission.SOCIAL_ACCOUNT_CONNECT,
        # organization and membership control
        Permission.ORG_UPDATE,
        Permission.ORG_MEMBER_MANAGE,
        # identity ownership
        Permission.INFLUENCER_CREATE,
        Permission.INFLUENCER_UPDATE,
        Permission.INFLUENCER_ARCHIVE,
        Permission.INFLUENCER_VERSION_CREATE,
        Permission.VOICE_MANAGE,
        Permission.EXPERIMENT_MANAGE,
    }
)

_OWNER_PERMISSIONS: frozenset[Permission] = frozenset(Permission)

_CREATIVE_LEAD_PERMISSIONS: frozenset[Permission] = READ_PERMISSIONS | {
    Permission.INFLUENCER_CREATE,
    Permission.INFLUENCER_UPDATE,
    Permission.INFLUENCER_ARCHIVE,
    Permission.INFLUENCER_VERSION_CREATE,
    Permission.ASSET_UPLOAD,
    Permission.ASSET_UPDATE,
    Permission.ASSET_ARCHIVE,
    Permission.ASSET_MARK_GOLDEN,
    Permission.VOICE_MANAGE,
    Permission.RECIPE_CREATE,
    Permission.RECIPE_UPDATE,
    Permission.RECIPE_VERSION_CREATE,
    Permission.CONTENT_CREATE,
    Permission.CONTENT_UPDATE,
    Permission.CONTENT_SCRIPT_CREATE,
    Permission.CONTENT_TRANSITION,
    Permission.JOB_CREATE,
    Permission.JOB_CANCEL,
    Permission.QA_CREATE,
    Permission.APPROVAL_REQUEST,
    # Scheduling is allowed; the domain service still requires an approved
    # ApprovalTask, so this is not a way around the approval gate.
    Permission.CALENDAR_SCHEDULE,
    Permission.EXPERIMENT_MANAGE,
    Permission.AUDIT_READ,
}

_OPERATOR_PERMISSIONS: frozenset[Permission] = READ_PERMISSIONS | {
    Permission.ASSET_UPLOAD,
    Permission.ASSET_UPDATE,
    Permission.CONTENT_CREATE,
    Permission.CONTENT_UPDATE,
    Permission.CONTENT_SCRIPT_CREATE,
    Permission.CONTENT_TRANSITION,
    Permission.JOB_CREATE,
    Permission.JOB_CANCEL,
    Permission.QA_CREATE,
    Permission.APPROVAL_REQUEST,
}

_REVIEWER_PERMISSIONS: frozenset[Permission] = READ_PERMISSIONS | {
    Permission.QA_CREATE,
    Permission.APPROVAL_REQUEST,
    Permission.APPROVAL_DECIDE,
    Permission.CONTENT_TRANSITION,
    Permission.AUDIT_READ,
}

_COMPLIANCE_PERMISSIONS: frozenset[Permission] = READ_PERMISSIONS | {
    Permission.POLICY_UPDATE,
    Permission.QA_CREATE,
    Permission.APPROVAL_REQUEST,
    Permission.APPROVAL_DECIDE,
    Permission.APPROVAL_DECIDE_HIGH_RISK,
    Permission.CONTENT_TRANSITION,
    Permission.AUDIT_READ,
}

_ANALYST_PERMISSIONS: frozenset[Permission] = READ_PERMISSIONS | {
    Permission.AUDIT_READ,
}

# The agent role is an automation identity: it may read production context and
# draft work, and it may queue generation jobs. It cannot alter identity, decide
# approvals, touch policy, or reach a publication surface.
_AGENT_PERMISSIONS: frozenset[Permission] = READ_PERMISSIONS | {
    Permission.CONTENT_CREATE,
    Permission.CONTENT_SCRIPT_CREATE,
    Permission.JOB_CREATE,
}

ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.OWNER: _OWNER_PERMISSIONS,
    Role.CREATIVE_LEAD: _CREATIVE_LEAD_PERMISSIONS,
    Role.OPERATOR: _OPERATOR_PERMISSIONS,
    Role.REVIEWER: _REVIEWER_PERMISSIONS,
    Role.COMPLIANCE: _COMPLIANCE_PERMISSIONS,
    Role.ANALYST: _ANALYST_PERMISSIONS,
    Role.AGENT: _AGENT_PERMISSIONS,
}


def permissions_for_role(role: Role) -> frozenset[Permission]:
    """Effective permissions for `role`, with the agent fence applied."""
    granted = ROLE_PERMISSIONS[role]
    if role is Role.AGENT:
        return granted - AGENT_FORBIDDEN_PERMISSIONS
    return granted


def role_has_permission(role: Role, permission: Permission) -> bool:
    """Whether `role` may perform `permission`."""
    if role is Role.AGENT and permission in AGENT_FORBIDDEN_PERMISSIONS:
        return False
    return permission in ROLE_PERMISSIONS[role]
