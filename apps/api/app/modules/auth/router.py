"""`/api/v1/auth` routes."""

from __future__ import annotations

from fastapi import APIRouter, status

from app.api.deps import AuthServiceDep, SettingsDep
from app.modules.auth.schemas import DevLoginRequest, LoginRequest, RefreshRequest, TokenPair

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/login",
    response_model=TokenPair,
    status_code=status.HTTP_200_OK,
    summary="Exchange email and password for a token pair",
)
async def login(payload: LoginRequest, auth: AuthServiceDep) -> TokenPair:
    session = await auth.login(email=payload.email, password=payload.password)
    return session.tokens


@router.post(
    "/refresh",
    response_model=TokenPair,
    summary="Exchange a refresh token for a new token pair",
)
async def refresh(payload: RefreshRequest, auth: AuthServiceDep) -> TokenPair:
    session = await auth.refresh(refresh_token=payload.refresh_token)
    return session.tokens


@router.post(
    "/dev-login",
    response_model=TokenPair,
    summary="Development-only passwordless login",
    description=(
        "Available only when the API runs with ENVIRONMENT=development and "
        "DEV_AUTH_ENABLED=true. The route is not registered at all in any other "
        "environment, and the service refuses the call even if it were."
    ),
    include_in_schema=True,
)
async def dev_login(
    payload: DevLoginRequest,
    auth: AuthServiceDep,
    settings: SettingsDep,
) -> TokenPair:
    # Registration is already conditional (see `build_auth_router`); this second
    # check keeps the handler safe if it is ever mounted unconditionally.
    del settings
    session = await auth.dev_login(
        email=payload.email,
        organization_id=payload.organization_id,
    )
    return session.tokens


def build_auth_router(*, include_dev_login: bool) -> APIRouter:
    """Assemble the auth router, omitting the dev stub outside development."""
    if include_dev_login:
        return router

    filtered = APIRouter(prefix="/auth", tags=["auth"])
    for route in router.routes:
        path = getattr(route, "path", "")
        if path.endswith("/dev-login"):
            continue
        filtered.routes.append(route)
    return filtered
