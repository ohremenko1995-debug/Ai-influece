"""RBAC matrix tests.

The matrix is the security boundary for the whole platform, so it is asserted
directly rather than only through endpoints. The agent-role tests encode the
platform rule that an automated actor can never publish, approve, change policy or
connect a social account.
"""

from __future__ import annotations

import uuid

import pytest

from app.core.actor import CurrentActor
from app.core.errors import PermissionDeniedError
from app.shared.permissions.matrix import (
    AGENT_FORBIDDEN_PERMISSIONS,
    ROLE_PERMISSIONS,
    permissions_for_role,
    role_has_permission,
)
from app.shared.permissions.permissions import READ_PERMISSIONS, Permission
from app.shared.permissions.roles import ActorType, Role

WRITE_PERMISSIONS = frozenset(Permission) - READ_PERMISSIONS


def test_every_role_is_in_the_matrix() -> None:
    """A new role without an entry would raise KeyError at request time."""
    assert set(ROLE_PERMISSIONS) == set(Role)


def test_owner_holds_every_permission() -> None:
    assert permissions_for_role(Role.OWNER) == frozenset(Permission)


def test_every_role_can_read() -> None:
    """Read access is the floor: every member can see the production context."""
    for role in Role:
        assert permissions_for_role(role) >= READ_PERMISSIONS, role


def test_analyst_is_read_only() -> None:
    granted = permissions_for_role(Role.ANALYST)
    assert not granted & WRITE_PERMISSIONS - {Permission.AUDIT_READ}
    assert Permission.AUDIT_READ in granted


# --- Separation of duties ----------------------------------------------------


@pytest.mark.parametrize("role", [Role.CREATIVE_LEAD, Role.OPERATOR, Role.AGENT, Role.ANALYST])
def test_content_producers_cannot_decide_approvals(role: Role) -> None:
    """Whoever makes the content must not be the one who signs it off."""
    assert not role_has_permission(role, Permission.APPROVAL_DECIDE)
    assert not role_has_permission(role, Permission.APPROVAL_DECIDE_HIGH_RISK)


@pytest.mark.parametrize("role", [Role.OWNER, Role.REVIEWER, Role.COMPLIANCE])
def test_reviewers_can_decide_approvals(role: Role) -> None:
    assert role_has_permission(role, Permission.APPROVAL_DECIDE)


@pytest.mark.parametrize("role", [Role.OWNER, Role.COMPLIANCE])
def test_high_risk_approval_is_limited_to_compliance_and_owner(role: Role) -> None:
    assert role_has_permission(role, Permission.APPROVAL_DECIDE_HIGH_RISK)


def test_plain_reviewer_cannot_approve_high_risk_content() -> None:
    assert role_has_permission(Role.REVIEWER, Permission.APPROVAL_DECIDE)
    assert not role_has_permission(Role.REVIEWER, Permission.APPROVAL_DECIDE_HIGH_RISK)


@pytest.mark.parametrize("role", [Role.OPERATOR, Role.REVIEWER, Role.ANALYST, Role.AGENT])
def test_only_owner_and_compliance_change_policy(role: Role) -> None:
    assert not role_has_permission(role, Permission.POLICY_UPDATE)


def test_policy_updates_are_limited_to_owner_and_compliance() -> None:
    allowed = {role for role in Role if role_has_permission(role, Permission.POLICY_UPDATE)}
    assert allowed == {Role.OWNER, Role.COMPLIANCE}


def test_only_owner_connects_social_accounts() -> None:
    allowed = {
        role for role in Role if role_has_permission(role, Permission.SOCIAL_ACCOUNT_CONNECT)
    }
    assert allowed == {Role.OWNER}


def test_scheduling_is_limited_to_owner_and_creative_lead() -> None:
    allowed = {role for role in Role if role_has_permission(role, Permission.CALENDAR_SCHEDULE)}
    assert allowed == {Role.OWNER, Role.CREATIVE_LEAD}


# --- The agent fence ---------------------------------------------------------


@pytest.mark.parametrize("permission", sorted(AGENT_FORBIDDEN_PERMISSIONS))
def test_agent_never_holds_a_forbidden_permission(permission: Permission) -> None:
    assert not role_has_permission(Role.AGENT, permission)
    assert permission not in permissions_for_role(Role.AGENT)


def test_agent_cannot_publish_approve_change_policy_or_connect_accounts() -> None:
    """The four capabilities named explicitly in the platform rules."""
    forbidden = {
        Permission.CALENDAR_PUBLISH_MARK,
        Permission.CALENDAR_SCHEDULE,
        Permission.APPROVAL_DECIDE,
        Permission.APPROVAL_DECIDE_HIGH_RISK,
        Permission.POLICY_UPDATE,
        Permission.SOCIAL_ACCOUNT_CONNECT,
    }
    assert not permissions_for_role(Role.AGENT) & forbidden


def test_agent_fence_survives_a_matrix_mistake(monkeypatch: pytest.MonkeyPatch) -> None:
    """Even if the table wrongly grants a forbidden permission, it is stripped.

    This is the defence-in-depth guarantee: the fence is applied after the table
    is read, so a bad edit cannot widen an automated actor's authority.
    """
    tampered = ROLE_PERMISSIONS[Role.AGENT] | {Permission.APPROVAL_DECIDE_HIGH_RISK}
    monkeypatch.setitem(ROLE_PERMISSIONS, Role.AGENT, tampered)

    assert Permission.APPROVAL_DECIDE_HIGH_RISK in ROLE_PERMISSIONS[Role.AGENT]
    assert not role_has_permission(Role.AGENT, Permission.APPROVAL_DECIDE_HIGH_RISK)
    assert Permission.APPROVAL_DECIDE_HIGH_RISK not in permissions_for_role(Role.AGENT)


def test_agent_may_still_draft_content_and_queue_jobs() -> None:
    """The fence must not make the role useless."""
    granted = permissions_for_role(Role.AGENT)
    assert Permission.CONTENT_CREATE in granted
    assert Permission.CONTENT_SCRIPT_CREATE in granted
    assert Permission.JOB_CREATE in granted


def test_agent_cannot_alter_influencer_identity() -> None:
    granted = permissions_for_role(Role.AGENT)
    assert Permission.INFLUENCER_CREATE not in granted
    assert Permission.INFLUENCER_UPDATE not in granted
    assert Permission.INFLUENCER_VERSION_CREATE not in granted


# --- CurrentActor enforcement ------------------------------------------------


def test_require_permission_raises_for_missing_permission() -> None:
    actor = CurrentActor.for_membership(
        organization_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        role=Role.OPERATOR,
        email="operator@example.com",
        display_name="Operator",
    )
    actor.require_permission(Permission.CONTENT_CREATE)
    with pytest.raises(PermissionDeniedError) as exc_info:
        actor.require_permission(Permission.APPROVAL_DECIDE)
    assert exc_info.value.details["required_permission"] == Permission.APPROVAL_DECIDE.value


def test_agent_role_produces_agent_actor_type() -> None:
    actor = CurrentActor.for_membership(
        organization_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        role=Role.AGENT,
        email="agent@example.com",
        display_name="Agent",
    )
    assert actor.actor_type is ActorType.AGENT


def test_system_actor_is_not_reachable_from_a_role() -> None:
    """A system actor holds everything, so it must never come from a membership."""
    system = CurrentActor.system(uuid.uuid4())
    assert system.actor_type is ActorType.SYSTEM
    assert system.permissions == frozenset(Permission)
    assert system.user_id is None
    assert system.role is None
