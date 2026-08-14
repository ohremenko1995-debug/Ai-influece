"""Single import point that attaches every ORM model to `Base.metadata`.

Alembic autogenerate and `create_all` only see mappers that have been imported.
Importing this module — and nothing else — guarantees the metadata is complete,
so a forgotten import cannot silently produce a migration that drops tables.

Modules from later MVP steps are added here as their models land.
"""

from __future__ import annotations

from app.modules.audit import models as audit_models
from app.modules.character_versions import models as character_version_models
from app.modules.influencers import models as influencer_models
from app.modules.organizations import models as organization_models
from app.modules.users import models as user_models
from app.shared.db.base import Base

__all__ = ["Base", "all_models"]


def all_models() -> tuple[type[Base], ...]:
    """Every mapped class, in dependency order. Used by tests and diagnostics."""
    return (
        organization_models.Organization,
        user_models.User,
        organization_models.Membership,
        influencer_models.DisclosurePolicy,
        influencer_models.Influencer,
        character_version_models.InfluencerVersion,
        audit_models.AuditLog,
    )
