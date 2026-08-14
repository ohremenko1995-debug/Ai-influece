"""End-to-end HTTP tests.

These go through the real router, dependencies, error handlers and response
models, so they cover what the service-level tests cannot: authentication,
authorization declared on routes, the error envelope and the OpenAPI contract.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.deps import ORGANIZATION_HEADER, get_session
from app.core.config import Environment, Settings
from app.main import create_app
from app.modules.influencers.models import InfluencerStatus
from app.modules.influencers.service import InfluencerService
from app.shared.db.session import Database
from app.shared.observability.middleware import REQUEST_ID_HEADER
from app.shared.permissions.roles import Role
from tests.conftest import TEST_PASSWORD

if TYPE_CHECKING:  # pragma: no cover - typing only
    from sqlalchemy.ext.asyncio import AsyncSession

    from tests.conftest import Tenant

pytestmark = pytest.mark.integration

INFLUENCER_BODY: dict[str, Any] = {
    "code": "nora",
    "public_name": "Nora",
    "primary_language": "en",
    "primary_market": "DE",
    "niche": "fitness",
}


async def _token(client: AsyncClient, tenant: Tenant, role: Role) -> str:
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": tenant.user(role).email, "password": TEST_PASSWORD},
        headers={ORGANIZATION_HEADER: str(tenant.organization.id)},
    )
    assert response.status_code == 200, response.text
    token: str = response.json()["access_token"]
    return token


async def _headers(client: AsyncClient, tenant: Tenant, role: Role) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {await _token(client, tenant, role)}",
        ORGANIZATION_HEADER: str(tenant.organization.id),
    }


# --- Health ------------------------------------------------------------------


async def test_liveness_is_unauthenticated(client: AsyncClient) -> None:
    response = await client.get("/health/live")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


async def test_request_id_is_echoed(client: AsyncClient) -> None:
    response = await client.get("/health/live", headers={REQUEST_ID_HEADER: "trace-me-123"})
    assert response.headers[REQUEST_ID_HEADER] == "trace-me-123"


async def test_request_id_is_generated_when_absent(client: AsyncClient) -> None:
    response = await client.get("/health/live")
    assert uuid.UUID(response.headers[REQUEST_ID_HEADER])


# --- Authentication ----------------------------------------------------------


async def test_login_returns_a_token_pair(client: AsyncClient, tenant: Tenant) -> None:
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": tenant.user(Role.OWNER).email, "password": TEST_PASSWORD},
        headers={ORGANIZATION_HEADER: str(tenant.organization.id)},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["refresh_token"]
    assert body["expires_in_seconds"] > 0


async def test_login_with_a_wrong_password_is_401(client: AsyncClient, tenant: Tenant) -> None:
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": tenant.user(Role.OWNER).email, "password": "not-the-password"},
    )
    assert response.status_code == 401
    error = response.json()["error"]
    assert error["code"] == "authentication_failed"
    # The message must not distinguish "no such user" from "wrong password".
    assert error["message"] == "Email or password is incorrect"


async def test_login_with_an_unknown_email_is_401(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": "nobody@example.com", "password": TEST_PASSWORD},
    )
    assert response.status_code == 401
    assert response.json()["error"]["message"] == "Email or password is incorrect"


async def test_refresh_issues_a_new_pair(client: AsyncClient, tenant: Tenant) -> None:
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": tenant.user(Role.OWNER).email, "password": TEST_PASSWORD},
    )
    refresh_token = login.json()["refresh_token"]
    response = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
    assert response.status_code == 200
    assert response.json()["access_token"]


async def test_access_token_is_rejected_by_the_refresh_endpoint(
    client: AsyncClient,
    tenant: Tenant,
) -> None:
    access = await _token(client, tenant, Role.OWNER)
    response = await client.post("/api/v1/auth/refresh", json={"refresh_token": access})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "token_wrong_type"


async def test_dev_login_works_in_development(client: AsyncClient, tenant: Tenant) -> None:
    response = await client.post(
        "/api/v1/auth/dev-login",
        json={
            "email": tenant.user(Role.OPERATOR).email,
            "organization_id": str(tenant.organization.id),
        },
    )
    assert response.status_code == 200
    assert response.json()["organization_id"] == str(tenant.organization.id)


def test_dev_login_route_does_not_exist_outside_development() -> None:
    """The stub is omitted from the router, not merely guarded inside it."""
    production = Settings(
        environment=Environment.PRODUCTION,
        dev_auth_enabled=False,
        secret_key="a-production-grade-secret-value-0123456789",
    )
    paths = create_app(production).openapi()["paths"]
    assert "/api/v1/auth/dev-login" not in paths
    assert "/api/v1/auth/login" in paths


# --- Authorization -----------------------------------------------------------


async def test_protected_route_without_a_token_is_401(client: AsyncClient) -> None:
    response = await client.get("/api/v1/influencers")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "token_missing"


async def test_garbage_token_is_401(client: AsyncClient) -> None:
    response = await client.get(
        "/api/v1/influencers",
        headers={"Authorization": "Bearer not-a-jwt"},
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "token_invalid"


async def test_organization_header_must_match_a_membership(
    client: AsyncClient,
    tenant: Tenant,
) -> None:
    """The header selects an organization; it never grants access to one."""
    token = await _token(client, tenant, Role.OWNER)
    response = await client.get(
        "/api/v1/influencers",
        headers={
            "Authorization": f"Bearer {token}",
            ORGANIZATION_HEADER: str(uuid.uuid4()),
        },
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "not_a_member"


async def test_me_reports_role_and_permissions(client: AsyncClient, tenant: Tenant) -> None:
    response = await client.get("/api/v1/me", headers=await _headers(client, tenant, Role.OPERATOR))
    assert response.status_code == 200
    body = response.json()
    assert body["active_role"] == Role.OPERATOR.value
    assert body["actor_type"] == "user"
    assert "content:create" in body["permissions"]
    assert "approval:decide" not in body["permissions"]
    assert body["user"]["email"] == tenant.user(Role.OPERATOR).email
    assert "password_hash" not in body["user"]


async def test_me_reports_agent_actor_type(client: AsyncClient, tenant: Tenant) -> None:
    response = await client.get("/api/v1/me", headers=await _headers(client, tenant, Role.AGENT))
    body = response.json()
    assert body["actor_type"] == "agent"
    for forbidden in (
        "approval:decide",
        "approval:decide_high_risk",
        "policy:update",
        "social_account:connect",
        "calendar:schedule",
        "calendar:publish_mark",
    ):
        assert forbidden not in body["permissions"], forbidden


@pytest.mark.parametrize(
    ("role", "expected"),
    [(Role.OWNER, 201), (Role.CREATIVE_LEAD, 201), (Role.OPERATOR, 403), (Role.AGENT, 403)],
)
async def test_influencer_creation_is_gated_by_role(
    client: AsyncClient,
    tenant: Tenant,
    role: Role,
    expected: int,
) -> None:
    response = await client.post(
        "/api/v1/influencers",
        json={**INFLUENCER_BODY, "code": f"nora-{role.value}"},
        headers=await _headers(client, tenant, role),
    )
    assert response.status_code == expected, response.text


# --- Influencer lifecycle over HTTP ------------------------------------------


async def test_create_read_update_and_activate(client: AsyncClient, tenant: Tenant) -> None:
    headers = await _headers(client, tenant, Role.OWNER)

    created = await client.post("/api/v1/influencers", json=INFLUENCER_BODY, headers=headers)
    assert created.status_code == 201
    influencer = created.json()
    assert influencer["status"] == InfluencerStatus.DRAFT.value
    assert len(influencer["activation_blockers"]) == 3

    influencer_id = influencer["id"]

    detail = await client.get(f"/api/v1/influencers/{influencer_id}", headers=headers)
    assert detail.status_code == 200
    assert detail.json()["current_version_number"] is None

    patched = await client.patch(
        f"/api/v1/influencers/{influencer_id}",
        json={
            "adult_representation_confirmed": True,
            "disclosure_policy_id": str(tenant.policy.id),
        },
        headers=headers,
    )
    assert patched.status_code == 200
    assert patched.json()["disclosure_policy"]["code"] == "default-ai-disclosure"

    blocked = await client.post(
        f"/api/v1/influencers/{influencer_id}/status",
        json={"status": "active"},
        headers=headers,
    )
    assert blocked.status_code == 422
    assert blocked.json()["error"]["code"] == "activation_blocked"

    version = await client.post(
        f"/api/v1/influencers/{influencer_id}/versions",
        json={
            "change_summary": "Initial identity",
            "biography": "Nora is a virtual fitness coach.",
            "personality_traits": ["disciplined"],
            "prohibited_topics": ["medical advice"],
            "visual_constraints": {"eye_color": "green"},
        },
        headers=headers,
    )
    assert version.status_code == 201
    assert version.json()["version_number"] == 1
    assert version.json()["is_current"] is True

    activated = await client.post(
        f"/api/v1/influencers/{influencer_id}/status",
        json={"status": "active", "reason": "Ready to launch"},
        headers=headers,
    )
    assert activated.status_code == 200
    assert activated.json()["status"] == InfluencerStatus.ACTIVE.value
    assert activated.json()["activation_blockers"] == []


async def test_invalid_transition_is_409(client: AsyncClient, tenant: Tenant) -> None:
    headers = await _headers(client, tenant, Role.OWNER)
    created = await client.post("/api/v1/influencers", json=INFLUENCER_BODY, headers=headers)
    influencer_id = created.json()["id"]

    response = await client.post(
        f"/api/v1/influencers/{influencer_id}/status",
        json={"status": "paused"},
        headers=headers,
    )
    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "invalid_transition"
    assert error["details"]["current_status"] == "draft"


async def test_duplicate_code_is_409(client: AsyncClient, tenant: Tenant) -> None:
    headers = await _headers(client, tenant, Role.OWNER)
    first = await client.post("/api/v1/influencers", json=INFLUENCER_BODY, headers=headers)
    assert first.status_code == 201
    second = await client.post("/api/v1/influencers", json=INFLUENCER_BODY, headers=headers)
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "conflict"


async def test_unknown_influencer_is_404(client: AsyncClient, tenant: Tenant) -> None:
    response = await client.get(
        f"/api/v1/influencers/{uuid.uuid4()}",
        headers=await _headers(client, tenant, Role.OWNER),
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


async def test_another_organizations_influencer_is_404_not_403(
    client: AsyncClient,
    tenant: Tenant,
    other_tenant: Tenant,
) -> None:
    created = await client.post(
        "/api/v1/influencers",
        json=INFLUENCER_BODY,
        headers=await _headers(client, tenant, Role.OWNER),
    )
    influencer_id = created.json()["id"]

    response = await client.get(
        f"/api/v1/influencers/{influencer_id}",
        headers=await _headers(client, other_tenant, Role.OWNER),
    )
    assert response.status_code == 404


async def test_version_history_is_paginated_newest_first(
    client: AsyncClient,
    tenant: Tenant,
) -> None:
    headers = await _headers(client, tenant, Role.OWNER)
    created = await client.post("/api/v1/influencers", json=INFLUENCER_BODY, headers=headers)
    influencer_id = created.json()["id"]

    for index in range(1, 4):
        response = await client.post(
            f"/api/v1/influencers/{influencer_id}/versions",
            json={"change_summary": f"Revision number {index}"},
            headers=headers,
        )
        assert response.status_code == 201

    listing = await client.get(
        f"/api/v1/influencers/{influencer_id}/versions",
        headers=headers,
        params={"limit": 2},
    )
    body = listing.json()
    assert body["total"] == 3
    assert [item["version_number"] for item in body["items"]] == [3, 2]

    current = await client.get(
        f"/api/v1/influencers/{influencer_id}/versions/current",
        headers=headers,
    )
    assert current.json()["version_number"] == 3

    historical = await client.get(
        f"/api/v1/influencers/{influencer_id}/versions/1",
        headers=headers,
    )
    assert historical.json()["change_summary"] == "Revision number 1"
    assert historical.json()["is_current"] is False


async def test_there_is_no_endpoint_to_modify_a_version(
    client: AsyncClient,
    tenant: Tenant,
) -> None:
    """Immutability is a property of the API surface, not only of the service."""
    headers = await _headers(client, tenant, Role.OWNER)
    created = await client.post("/api/v1/influencers", json=INFLUENCER_BODY, headers=headers)
    influencer_id = created.json()["id"]
    await client.post(
        f"/api/v1/influencers/{influencer_id}/versions",
        json={"change_summary": "Initial identity"},
        headers=headers,
    )

    for method in ("patch", "put", "delete"):
        response = await client.request(
            method.upper(),
            f"/api/v1/influencers/{influencer_id}/versions/1",
            headers=headers,
        )
        assert response.status_code == 405, method


# --- Validation and error envelope -------------------------------------------


async def test_unknown_body_fields_are_rejected(client: AsyncClient, tenant: Tenant) -> None:
    response = await client.post(
        "/api/v1/influencers",
        json={**INFLUENCER_BODY, "status": "active"},
        headers=await _headers(client, tenant, Role.OWNER),
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "request_validation_error"


@pytest.mark.parametrize(
    "override",
    [
        {"code": "NoRa"},
        {"code": "a"},
        {"primary_language": "english"},
        {"primary_market": "de"},
        {"public_name": ""},
    ],
)
async def test_invalid_field_values_are_422(
    client: AsyncClient,
    tenant: Tenant,
    override: dict[str, Any],
) -> None:
    response = await client.post(
        "/api/v1/influencers",
        json={**INFLUENCER_BODY, **override},
        headers=await _headers(client, tenant, Role.OWNER),
    )
    assert response.status_code == 422, override


async def test_error_envelope_carries_the_request_id(client: AsyncClient) -> None:
    response = await client.get(
        "/api/v1/influencers",
        headers={REQUEST_ID_HEADER: "corr-1"},
    )
    assert response.status_code == 401
    assert response.json()["error"]["request_id"] == "corr-1"


# --- Audit log over HTTP -----------------------------------------------------


async def test_audit_log_shows_the_actions_taken(client: AsyncClient, tenant: Tenant) -> None:
    headers = await _headers(client, tenant, Role.OWNER)
    created = await client.post("/api/v1/influencers", json=INFLUENCER_BODY, headers=headers)
    influencer_id = created.json()["id"]
    await client.patch(
        f"/api/v1/influencers/{influencer_id}",
        json={"public_name": "Nora Prime"},
        headers=headers,
    )

    history = await client.get(
        f"/api/v1/influencers/{influencer_id}/audit-logs",
        headers=headers,
    )
    assert history.status_code == 200
    body = history.json()
    actions = [item["entry"]["action"] for item in body["items"]]
    assert actions == ["influencer.updated", "influencer.created"]
    assert body["items"][0]["changed_fields"]["public_name"] == {
        "from": "Nora",
        "to": "Nora Prime",
    }
    # A creation has no previous state, so no diff is reported for it.
    assert body["items"][-1]["changed_fields"] == {}


async def test_login_is_recorded_in_the_audit_log(client: AsyncClient, tenant: Tenant) -> None:
    headers = await _headers(client, tenant, Role.OWNER)
    response = await client.get(
        "/api/v1/audit-logs",
        headers=headers,
        params={"action": "auth.login_succeeded"},
    )
    assert response.status_code == 200
    assert response.json()["total"] >= 1


async def test_audit_log_requires_the_audit_permission(
    client: AsyncClient,
    tenant: Tenant,
) -> None:
    response = await client.get(
        "/api/v1/audit-logs", headers=await _headers(client, tenant, Role.OPERATOR)
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "permission_denied"


async def test_audit_log_has_no_write_endpoint(client: AsyncClient, tenant: Tenant) -> None:
    headers = await _headers(client, tenant, Role.OWNER)
    for method in ("POST", "PATCH", "DELETE"):
        response = await client.request(method, "/api/v1/audit-logs", headers=headers)
        assert response.status_code == 405, method


# --- Organization members ----------------------------------------------------


async def test_members_listing_includes_every_role(client: AsyncClient, tenant: Tenant) -> None:
    response = await client.get(
        "/api/v1/organizations/current/members",
        headers=await _headers(client, tenant, Role.OWNER),
    )
    assert response.status_code == 200
    roles = {member["role"] for member in response.json()}
    assert roles == {role.value for role in Role}


async def test_role_change_requires_member_management(
    client: AsyncClient,
    tenant: Tenant,
) -> None:
    target = tenant.user(Role.ANALYST).id
    response = await client.patch(
        f"/api/v1/organizations/current/members/{target}",
        json={"role": "reviewer"},
        headers=await _headers(client, tenant, Role.CREATIVE_LEAD),
    )
    assert response.status_code == 403


async def test_owner_cannot_revoke_their_own_membership(
    client: AsyncClient,
    tenant: Tenant,
) -> None:
    owner_id = tenant.user(Role.OWNER).id
    response = await client.delete(
        f"/api/v1/organizations/current/members/{owner_id}",
        headers=await _headers(client, tenant, Role.OWNER),
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "cannot_revoke_self"


# --- Contract ----------------------------------------------------------------


async def test_openapi_document_is_served(client: AsyncClient) -> None:
    response = await client.get("/openapi.json")
    assert response.status_code == 200
    document = response.json()
    assert document["info"]["title"] == "InfluencerOS API"
    assert "/api/v1/influencers" in document["paths"]


async def test_every_v1_route_is_under_the_version_prefix(client: AsyncClient) -> None:
    document = (await client.get("/openapi.json")).json()
    non_health = [path for path in document["paths"] if not path.startswith("/health")]
    assert non_health
    assert all(path.startswith("/api/v1/") for path in non_health)


# --- Regressions -------------------------------------------------------------


async def test_creating_with_a_policy_returns_the_resolved_policy(
    client: AsyncClient,
    tenant: Tenant,
) -> None:
    """Regression: creating *with* a disclosure policy used to fail with 500.

    The new `Influencer` had the foreign key set but the relationship unloaded, so
    serialising the response attempted a lazy load inside an async request.
    """
    response = await client.post(
        "/api/v1/influencers",
        json={
            **INFLUENCER_BODY,
            "adult_representation_confirmed": True,
            "disclosure_policy_id": str(tenant.policy.id),
        },
        headers=await _headers(client, tenant, Role.OWNER),
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["disclosure_policy"]["code"] == "default-ai-disclosure"
    assert body["disclosure_policy"]["ai_disclosure_required"] is True
    # Only the Character Bible is still missing.
    assert body["activation_blockers"] == ["a Character Bible version must exist"]


async def test_full_activation_path_over_http(client: AsyncClient, tenant: Tenant) -> None:
    """Acceptance path: create Nora, add Character Bible v1, activate, audit."""
    headers = await _headers(client, tenant, Role.OWNER)

    created = await client.post(
        "/api/v1/influencers",
        json={
            "code": "nora",
            "public_name": "Nora",
            "primary_language": "en",
            "primary_market": "DE",
            "niche": "fitness",
            "adult_representation_confirmed": True,
            "disclosure_policy_id": str(tenant.policy.id),
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    influencer_id = created.json()["id"]

    bible = await client.post(
        f"/api/v1/influencers/{influencer_id}/versions",
        json={
            "change_summary": "Initial Character Bible",
            "biography": "Nora is a transparent virtual fitness coach.",
            "tone_of_voice": "Direct, warm",
            "personality_traits": ["disciplined"],
            "prohibited_topics": ["medical advice"],
            "visual_constraints": {"eye_color": "green"},
        },
        headers=headers,
    )
    assert bible.status_code == 201, bible.text

    activated = await client.post(
        f"/api/v1/influencers/{influencer_id}/status",
        json={"status": "active", "reason": "Launch"},
        headers=headers,
    )
    assert activated.status_code == 200, activated.text
    assert activated.json()["status"] == "active"

    history = await client.get(f"/api/v1/influencers/{influencer_id}/audit-logs", headers=headers)
    actions = [item["entry"]["action"] for item in history.json()["items"]]
    assert actions == [
        "influencer.status_changed",
        "influencer_version.promoted",
        "influencer.created",
    ]


async def test_error_envelope_keeps_the_request_id_on_a_server_error(
    settings: Settings,
    database: Database,
    session: AsyncSession,
    client: AsyncClient,
    tenant: Tenant,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression: 500 responses used to report `request_id: null`.

    The request-context middleware resets its context var before Starlette's
    server-error handler runs, so the id has to come from `request.state`.

    Uses its own transport with `raise_app_exceptions=False`: Starlette's
    server-error middleware re-raises after sending the 500, which the shared
    client would surface as a test error instead of a response.
    """
    headers = {**await _headers(client, tenant, Role.OWNER), REQUEST_ID_HEADER: "corr-500"}

    def _boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("induced failure")

    monkeypatch.setattr(InfluencerService, "list_influencers", _boom)

    app = create_app(settings)
    app.state.database = database
    app.dependency_overrides[get_session] = lambda: session
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://testserver") as failing:
        response = await failing.get("/api/v1/influencers", headers=headers)

    assert response.status_code == 500
    error = response.json()["error"]
    assert error["code"] == "internal_error"
    assert error["request_id"] == "corr-500"
    # Nothing internal leaks to the caller.
    assert "induced failure" not in response.text
