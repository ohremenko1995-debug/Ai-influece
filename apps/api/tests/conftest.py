"""Test fixtures.

Tests run against a real PostgreSQL 16 database (`POSTGRES_TEST_DB`), not SQLite.
The schema uses JSONB, partial unique indexes and CHECK constraints, so a
different engine would validate a different system.

The schema is built by running the Alembic migrations, which means every test run
also verifies that the migrations apply — and that `downgrade` works.

Isolation: each test gets a connection with an open transaction and a session
joined to it via a savepoint. Application code commits normally; the outer
transaction is rolled back afterwards, so no test sees another's rows.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest
import pytest_asyncio
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from alembic import command
from app.api.deps import get_session
from app.core.actor import CurrentActor
from app.core.config import Environment, Settings
from app.core.security import hash_password
from app.modules.audit.service import AuditService
from app.modules.character_versions.repository import InfluencerVersionRepository
from app.modules.character_versions.service import InfluencerVersionService
from app.modules.influencers.models import DisclosurePolicy
from app.modules.influencers.repository import DisclosurePolicyRepository, InfluencerRepository
from app.modules.influencers.service import InfluencerService
from app.modules.organizations.models import Organization
from app.modules.organizations.repository import MembershipRepository, OrganizationRepository
from app.modules.users.models import User, UserStatus
from app.modules.users.repository import UserRepository
from app.shared.db.session import Database
from app.shared.permissions.roles import Role

API_DIR = Path(__file__).resolve().parent.parent
TEST_PASSWORD = "test-password-1234"

# Hashed once for the whole session. argon2 is deliberately expensive (~100ms),
# and every test seeds seven users, so re-hashing per user would dominate the
# suite's runtime. `test_config_and_security.py` covers the hashing itself.
TEST_PASSWORD_HASH = hash_password(TEST_PASSWORD)


@pytest.fixture(scope="session")
def settings() -> Settings:
    """Settings pointed at the test database.

    `environment` stays `development` so the dev-login stub is reachable and can
    be tested; the production-safety rules are covered separately in
    `test_config.py` without touching a database.
    """
    base = Settings()
    return Settings(
        environment=Environment.DEVELOPMENT,
        dev_auth_enabled=True,
        postgres_host=base.postgres_host,
        postgres_port=base.postgres_port,
        postgres_user=base.postgres_user,
        postgres_password=base.postgres_password,
        postgres_db=base.postgres_test_db,
        secret_key="test-secret-key-not-used-outside-tests",
        log_level="WARNING",
    )


@pytest.fixture(scope="session")
def migrated_schema(settings: Settings, monkeypatch_session: pytest.MonkeyPatch) -> None:
    """Rebuild the test schema by running the migrations.

    Runs `downgrade base` first so a previous run's tables cannot mask a missing
    `upgrade` step, then `upgrade head`. Both directions therefore execute on
    every test session.
    """
    monkeypatch_session.setenv("ALEMBIC_DATABASE_URL", settings.database_url)
    config = Config(str(API_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(API_DIR / "alembic"))
    command.downgrade(config, "base")
    command.upgrade(config, "head")


@pytest.fixture(scope="session")
def monkeypatch_session() -> Iterator[pytest.MonkeyPatch]:
    """Session-scoped monkeypatch (the built-in fixture is function-scoped)."""
    patcher = pytest.MonkeyPatch()
    yield patcher
    patcher.undo()


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def database(settings: Settings, migrated_schema: None) -> AsyncIterator[Database]:
    del migrated_schema  # ordering dependency only
    instance = Database(settings.database_url, pool_size=5, max_overflow=0)
    yield instance
    await instance.dispose()


@pytest_asyncio.fixture(loop_scope="session")
async def session(database: Database) -> AsyncIterator[AsyncSession]:
    """A session whose writes are discarded when the test ends.

    `join_transaction_mode="create_savepoint"` lets application code call
    `commit()` for real — it commits a savepoint inside the fixture's transaction,
    which is then rolled back.
    """
    async with database.engine.connect() as connection:
        transaction = await connection.begin()
        db_session = AsyncSession(
            bind=connection,
            expire_on_commit=False,
            autoflush=False,
            join_transaction_mode="create_savepoint",
        )
        try:
            yield db_session
        finally:
            await db_session.close()
            await transaction.rollback()


# --- Domain fixtures ---------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Tenant:
    """A seeded organization with one user per role."""

    organization: Organization
    policy: DisclosurePolicy
    users: dict[Role, User]

    def actor(self, role: Role) -> CurrentActor:
        user = self.users[role]
        return CurrentActor.for_membership(
            organization_id=self.organization.id,
            user_id=user.id,
            role=role,
            email=user.email,
            display_name=user.display_name,
        )

    def user(self, role: Role) -> User:
        return self.users[role]


async def _build_tenant(session: AsyncSession, *, slug: str) -> Tenant:
    user_repo = UserRepository(session)
    organizations = OrganizationRepository(session)
    memberships = MembershipRepository(session)
    policies = DisclosurePolicyRepository(session)

    organization = await organizations.create(name=f"Org {slug}", slug=slug)
    created: dict[Role, User] = {}
    for role in Role:
        user = await user_repo.create(
            email=f"{role.value}-{slug}@example.com",
            display_name=f"{role.value.title()} {slug}",
            status=UserStatus.ACTIVE,
            password_hash=TEST_PASSWORD_HASH,
        )
        await memberships.create(
            organization_id=organization.id,
            user_id=user.id,
            role=role,
        )
        created[role] = user

    policy = DisclosurePolicy(
        organization_id=organization.id,
        code="default-ai-disclosure",
        name="Default disclosure",
        ai_disclosure_required=True,
        ai_disclosure_text="This character is a virtual persona generated with AI.",
        advertising_disclosure_required=True,
        advertising_disclosure_text="Paid partnership. #ad",
        requires_high_risk_approval=True,
        is_default=True,
    )
    await policies.create(policy)
    await session.flush()
    return Tenant(organization=organization, policy=policy, users=created)


@pytest_asyncio.fixture(loop_scope="session")
async def tenant(session: AsyncSession) -> Tenant:
    """The organization under test, with one active member per role."""
    return await _build_tenant(session, slug=f"acme-{uuid.uuid4().hex[:8]}")


@pytest_asyncio.fixture(loop_scope="session")
async def other_tenant(session: AsyncSession) -> Tenant:
    """A second organization, used to prove cross-tenant isolation."""
    return await _build_tenant(session, slug=f"rival-{uuid.uuid4().hex[:8]}")


# --- Service fixtures --------------------------------------------------------


@pytest.fixture
def audit_service(session: AsyncSession) -> AuditService:
    return AuditService(session)


@pytest.fixture
def influencer_service(session: AsyncSession, audit_service: AuditService) -> InfluencerService:
    return InfluencerService(
        influencers=InfluencerRepository(session),
        policies=DisclosurePolicyRepository(session),
        versions=InfluencerVersionRepository(session),
        audit=audit_service,
    )


@pytest.fixture
def version_service(
    session: AsyncSession,
    audit_service: AuditService,
) -> InfluencerVersionService:
    return InfluencerVersionService(
        influencers=InfluencerRepository(session),
        versions=InfluencerVersionRepository(session),
        audit=audit_service,
    )


# --- HTTP fixtures -----------------------------------------------------------


@pytest_asyncio.fixture(loop_scope="session")
async def client(
    settings: Settings,
    database: Database,
    session: AsyncSession,
) -> AsyncIterator[AsyncClient]:
    """An HTTP client wired to the app, sharing the test's transaction.

    The `get_session` dependency is overridden so requests write through the same
    savepoint-backed session the test uses, keeping assertions and requests
    consistent — and rolled back together.
    """
    from app.main import create_app  # noqa: PLC0415 - avoid app construction at import

    app = create_app(settings)
    app.state.database = database
    app.dependency_overrides[get_session] = lambda: session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as http:
        yield http
    app.dependency_overrides.clear()
