"""`/api/v1` router assembly.

Route groups from later MVP steps (`/assets`, `/recipes`, `/content`,
`/generation-jobs`, `/qa`, `/approvals`, `/calendar`, `/experiments`,
`/dashboard`) are mounted here as their modules land. They are not registered as
empty stubs, so the generated OpenAPI document never advertises an endpoint that
does not work.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.core.config import Settings
from app.modules.audit.router import router as audit_router
from app.modules.auth.router import build_auth_router
from app.modules.influencers.router import policies_router
from app.modules.influencers.router import router as influencers_router
from app.modules.organizations.router import router as organizations_router
from app.modules.users.router import router as me_router

API_V1_PREFIX = "/api/v1"


def build_v1_router(settings: Settings) -> APIRouter:
    """Compose every module router available in this MVP step."""
    router = APIRouter(prefix=API_V1_PREFIX)
    router.include_router(build_auth_router(include_dev_login=settings.dev_auth_active))
    router.include_router(me_router)
    router.include_router(organizations_router)
    router.include_router(influencers_router)
    router.include_router(policies_router)
    router.include_router(audit_router)
    return router
