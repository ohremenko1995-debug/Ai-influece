"""Operator CLI: `python -m app.cli <command>`.

Two commands: export the OpenAPI document (used to generate the frontend's types)
and seed a local development organization.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Annotated

import typer

from app.core.actor import CurrentActor
from app.core.config import Environment, get_settings
from app.core.security import hash_password
from app.modules.audit.service import AuditService
from app.modules.influencers.models import DisclosurePolicy
from app.modules.influencers.repository import DisclosurePolicyRepository
from app.modules.organizations.repository import MembershipRepository, OrganizationRepository
from app.modules.organizations.service import OrganizationService
from app.modules.users.models import UserStatus
from app.modules.users.repository import UserRepository
from app.shared.db.session import build_database
from app.shared.events.actions import DomainAction
from app.shared.permissions.roles import Role

cli = typer.Typer(add_completion=False, help="InfluencerOS API operator commands")

# Local-development credentials. Seeding refuses to run outside development, so
# these never reach a real environment.
SEED_PASSWORD = "influenceros"  # noqa: S105 - development seed only
SEED_ORGANIZATION_NAME = "InfluencerOS Studio"
SEED_ORGANIZATION_SLUG = "influenceros-studio"
SEED_USERS: tuple[tuple[str, str, Role], ...] = (
    ("owner@influenceros.example.com", "Ola Owner", Role.OWNER),
    ("creative@influenceros.example.com", "Cleo Creative Lead", Role.CREATIVE_LEAD),
    ("operator@influenceros.example.com", "Omar Operator", Role.OPERATOR),
    ("reviewer@influenceros.example.com", "Rin Reviewer", Role.REVIEWER),
    ("compliance@influenceros.example.com", "Cam Compliance", Role.COMPLIANCE),
    ("analyst@influenceros.example.com", "Ada Analyst", Role.ANALYST),
    ("agent@influenceros.example.com", "Automation Agent", Role.AGENT),
)


@cli.command("export-openapi")
def export_openapi(
    output: Annotated[Path, typer.Option("--output", "-o", help="Destination file")],
) -> None:
    """Write the OpenAPI document to a file.

    Imports the app rather than calling a running server, so the contract can be
    regenerated in CI without booting the stack.
    """
    # Imported here, not at module scope: `app.main` builds an application
    # instance on import, which the `seed` command has no use for.
    from app.main import create_app  # noqa: PLC0415

    app = create_app()
    document = app.openapi()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    typer.echo(f"Wrote {output} ({len(document.get('paths', {}))} paths)")


@cli.command("seed")
def seed() -> None:
    """Create the development organization, one user per role, and a policy.

    Idempotent: re-running adds only what is missing.
    """
    settings = get_settings()
    if settings.environment is not Environment.DEVELOPMENT:
        typer.echo(
            f"Refusing to seed: ENVIRONMENT is '{settings.environment.value}', not 'development'.",
            err=True,
        )
        raise typer.Exit(code=1)
    asyncio.run(_seed())


async def _seed() -> None:
    settings = get_settings()
    database = build_database(settings)
    try:
        async with database.session() as session:
            users = UserRepository(session)
            organizations = OrganizationRepository(session)
            memberships = MembershipRepository(session)
            audit = AuditService(session)
            policies = DisclosurePolicyRepository(session)
            org_service = OrganizationService(
                organizations=organizations,
                memberships=memberships,
                audit=audit,
            )

            # 1. Users -------------------------------------------------------
            created_users = {}
            for email, display_name, role in SEED_USERS:
                user = await users.get_by_email(email)
                if user is None:
                    user = await users.create(
                        email=email,
                        display_name=display_name,
                        status=UserStatus.ACTIVE,
                        password_hash=hash_password(SEED_PASSWORD),
                    )
                    typer.echo(f"created user {email}")
                created_users[role] = user

            # 2. Organization + owner membership ----------------------------
            organization = await organizations.get_by_slug(SEED_ORGANIZATION_SLUG)
            if organization is None:
                organization, _ = await org_service.create_with_owner(
                    name=SEED_ORGANIZATION_NAME,
                    slug=SEED_ORGANIZATION_SLUG,
                    owner_user_id=created_users[Role.OWNER].id,
                )
                typer.echo(f"created organization {organization.slug}")

            system_actor = CurrentActor.system(organization.id)

            # 3. Remaining memberships --------------------------------------
            for _, _, role in SEED_USERS:
                if role is Role.OWNER:
                    continue
                user = created_users[role]
                existing = await memberships.get_active(
                    user_id=user.id,
                    organization_id=organization.id,
                )
                if existing is None:
                    membership = await memberships.create(
                        organization_id=organization.id,
                        user_id=user.id,
                        role=role,
                    )
                    await audit.record_entity_change(
                        actor=system_actor,
                        action=DomainAction.MEMBERSHIP_CREATED,
                        entity=membership,
                    )
                    typer.echo(f"created membership {user.email} -> {role.value}")

            # 4. Default disclosure policy ----------------------------------
            policy = await policies.get_by_code(
                organization_id=organization.id,
                code="default-ai-disclosure",
            )
            if policy is None:
                policy = DisclosurePolicy(
                    organization_id=organization.id,
                    code="default-ai-disclosure",
                    name="Default AI and advertising disclosure",
                    ai_disclosure_required=True,
                    ai_disclosure_text=(
                        "This character is a virtual persona. All imagery and speech "
                        "are generated with AI."
                    ),
                    advertising_disclosure_required=True,
                    advertising_disclosure_text="Paid partnership. #ad",
                    requires_high_risk_approval=True,
                    is_default=True,
                    notes="Seeded default. Review before using outside local development.",
                )
                await policies.create(policy)
                await audit.record_entity_change(
                    actor=system_actor,
                    action=DomainAction.DISCLOSURE_POLICY_CREATED,
                    entity=policy,
                )
                typer.echo(f"created disclosure policy {policy.code}")

        typer.echo("")
        typer.echo(f"Seed complete. Organization: {SEED_ORGANIZATION_SLUG}")
        typer.echo(f"Sign in with any seeded email and password '{SEED_PASSWORD}':")
        for email, _, role in SEED_USERS:
            typer.echo(f"  {role.value:<14} {email}")
    finally:
        await database.dispose()


if __name__ == "__main__":
    cli()
