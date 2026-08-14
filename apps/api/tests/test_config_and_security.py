"""Settings validation and auth primitives.

No database involved: these guard the boot-time refusals and the token/password
handling that everything else depends on.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from app.core.config import DEV_SECRET_KEY, Environment, Settings
from app.core.errors import AuthenticationError
from app.core.security import (
    TokenType,
    create_token,
    decode_token,
    hash_password,
    verify_password,
)

REAL_SECRET = "a-sufficiently-long-secret-for-tests-0123456789"


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "environment": Environment.DEVELOPMENT,
        "secret_key": REAL_SECRET,
        "dev_auth_enabled": False,
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


# --- Settings ----------------------------------------------------------------


def test_production_refuses_the_development_secret() -> None:
    with pytest.raises(ValueError, match="development placeholder"):
        _settings(environment=Environment.PRODUCTION, secret_key=DEV_SECRET_KEY)


def test_production_refuses_a_short_secret() -> None:
    with pytest.raises(ValueError, match="at least 32 characters"):
        _settings(environment=Environment.PRODUCTION, secret_key="too-short")


def test_production_refuses_dev_auth() -> None:
    with pytest.raises(ValueError, match="DEV_AUTH_ENABLED must be false"):
        _settings(environment=Environment.PRODUCTION, dev_auth_enabled=True)


def test_staging_is_validated_like_production() -> None:
    with pytest.raises(ValueError, match="DEV_AUTH_ENABLED must be false"):
        _settings(environment=Environment.STAGING, dev_auth_enabled=True)


def test_development_tolerates_placeholders() -> None:
    settings = _settings(secret_key=DEV_SECRET_KEY, dev_auth_enabled=True)
    assert settings.dev_auth_active is True


def test_wildcard_cors_origin_is_rejected() -> None:
    with pytest.raises(ValueError, match="never '\\*'"):
        _settings(api_cors_origins="*")


@pytest.mark.parametrize(
    ("environment", "flag", "expected"),
    [
        (Environment.DEVELOPMENT, True, True),
        (Environment.DEVELOPMENT, False, False),
        (Environment.TEST, True, False),
    ],
)
def test_dev_auth_needs_both_the_flag_and_the_environment(
    environment: Environment,
    flag: bool,
    expected: bool,
) -> None:
    """Flipping one variable must not be enough to enable passwordless login."""
    assert _settings(environment=environment, dev_auth_enabled=flag).dev_auth_active is expected


def test_database_urls_are_distinct() -> None:
    settings = _settings(postgres_db="app_db", postgres_test_db="app_db_test")
    assert settings.database_url.endswith("/app_db")
    assert settings.test_database_url.endswith("/app_db_test")
    assert settings.database_url.startswith("postgresql+asyncpg://")


def test_cors_origins_are_split_and_trimmed() -> None:
    settings = _settings(api_cors_origins="http://a.test, http://b.test ,")
    assert settings.cors_origin_list == ["http://a.test", "http://b.test"]


# --- Passwords ---------------------------------------------------------------


def test_password_round_trip() -> None:
    stored = hash_password("correct horse battery staple")
    assert stored != "correct horse battery staple"
    assert verify_password("correct horse battery staple", stored)
    assert not verify_password("wrong password", stored)


def test_verify_against_a_missing_hash_is_false_not_an_error() -> None:
    """Unknown accounts must take the same code path as wrong passwords."""
    assert verify_password("anything", None) is False


def test_hashes_are_salted() -> None:
    assert hash_password("same") != hash_password("same")


# --- Tokens ------------------------------------------------------------------


def test_access_token_round_trip() -> None:
    settings = _settings()
    subject = uuid.uuid4()
    organization = uuid.uuid4()
    token = create_token(
        settings=settings,
        subject=subject,
        token_type=TokenType.ACCESS,
        organization_id=organization,
    )
    claims = decode_token(settings=settings, token=token, expected_type=TokenType.ACCESS)
    assert claims.subject == subject
    assert claims.organization_id == organization


def test_refresh_token_is_rejected_where_an_access_token_is_required() -> None:
    settings = _settings()
    token = create_token(
        settings=settings,
        subject=uuid.uuid4(),
        token_type=TokenType.REFRESH,
    )
    with pytest.raises(AuthenticationError) as exc_info:
        decode_token(settings=settings, token=token, expected_type=TokenType.ACCESS)
    assert exc_info.value.code == "token_wrong_type"


def test_token_signed_with_another_key_is_rejected() -> None:
    issuer = _settings()
    verifier = _settings(secret_key="a-different-secret-of-adequate-length-9876")
    token = create_token(settings=issuer, subject=uuid.uuid4(), token_type=TokenType.ACCESS)
    with pytest.raises(AuthenticationError) as exc_info:
        decode_token(settings=verifier, token=token, expected_type=TokenType.ACCESS)
    assert exc_info.value.code == "token_invalid"


def test_expired_token_is_reported_as_expired() -> None:
    settings = _settings()
    issued = datetime.now(UTC) - timedelta(hours=2)
    token = jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "typ": TokenType.ACCESS.value,
            "iat": issued,
            "exp": issued + timedelta(minutes=1),
            "jti": str(uuid.uuid4()),
        },
        settings.secret_key,
        algorithm=settings.jwt_algorithm,
    )
    with pytest.raises(AuthenticationError) as exc_info:
        decode_token(settings=settings, token=token, expected_type=TokenType.ACCESS)
    assert exc_info.value.code == "token_expired"


def test_token_without_required_claims_is_rejected() -> None:
    settings = _settings()
    token = jwt.encode({"sub": str(uuid.uuid4())}, settings.secret_key, algorithm="HS256")
    with pytest.raises(AuthenticationError):
        decode_token(settings=settings, token=token, expected_type=TokenType.ACCESS)


def test_unsigned_token_is_rejected() -> None:
    """`alg: none` must not be accepted."""
    settings = _settings()
    token = jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "typ": TokenType.ACCESS.value,
            "iat": datetime.now(UTC),
            "exp": datetime.now(UTC) + timedelta(minutes=5),
            "jti": str(uuid.uuid4()),
        },
        key="",
        algorithm="none",
    )
    with pytest.raises(AuthenticationError):
        decode_token(settings=settings, token=token, expected_type=TokenType.ACCESS)
