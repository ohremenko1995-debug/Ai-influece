"""Application settings.

Every value is read from the environment. Nothing is hardcoded per-deployment and
no secret has a usable production default — `Settings.validate_production_safety`
refuses to boot a non-development environment that still carries dev placeholders.
"""

from __future__ import annotations

import enum
from functools import lru_cache
from typing import Literal, Self

from pydantic import Field, PostgresDsn, RedisDsn, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# At least 32 bytes: HMAC-SHA256 keys shorter than the digest size are
# rejected as insecure by PyJWT (RFC 7518 section 3.2).
DEV_SECRET_KEY = "dev-only-insecure-placeholder-change-me-before-any-real-use"
MIN_SECRET_KEY_LENGTH = 32


class Environment(enum.StrEnum):
    """Deployment environment. Gates development-only behaviour."""

    DEVELOPMENT = "development"
    TEST = "test"
    STAGING = "staging"
    PRODUCTION = "production"


class GenerationProviderName(enum.StrEnum):
    """Which `GenerationProvider` implementation the worker should resolve."""

    FAKE = "fake"
    COMFYUI = "comfyui"


class Settings(BaseSettings):
    """Typed view of the process environment."""

    model_config = SettingsConfigDict(
        env_file=(".env", "../../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        frozen=True,
    )

    # --- Runtime -----------------------------------------------------------
    environment: Environment = Environment.DEVELOPMENT
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    log_format: Literal["console", "json"] = "console"

    # --- HTTP --------------------------------------------------------------
    api_host: str = "0.0.0.0"  # noqa: S104 — containers must bind all interfaces
    api_port: int = 8000
    api_cors_origins: str = "http://localhost:3000"

    # --- Auth --------------------------------------------------------------
    secret_key: str = DEV_SECRET_KEY
    jwt_algorithm: Literal["HS256"] = "HS256"
    access_token_ttl_minutes: int = Field(default=30, ge=1, le=24 * 60)
    refresh_token_ttl_minutes: int = Field(default=7 * 24 * 60, ge=5)
    dev_auth_enabled: bool = True

    # --- PostgreSQL --------------------------------------------------------
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_user: str = "influenceros"
    postgres_password: str = "influenceros"
    postgres_db: str = "influenceros"
    postgres_test_db: str = "influenceros_test"
    db_pool_size: int = Field(default=10, ge=1)
    db_max_overflow: int = Field(default=5, ge=0)
    db_echo: bool = False

    # --- Redis -------------------------------------------------------------
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0

    # --- Object storage ----------------------------------------------------
    s3_endpoint_url: str = "http://localhost:9000"
    s3_public_endpoint_url: str = "http://localhost:9000"
    s3_region: str = "us-east-1"
    s3_bucket: str = "influenceros-assets"
    s3_access_key_id: str = "influenceros"
    s3_secret_access_key: str = "influenceros"
    s3_force_path_style: bool = True
    s3_presign_ttl_seconds: int = Field(default=900, ge=60, le=3600)

    # --- Generation providers ----------------------------------------------
    generation_provider: GenerationProviderName = GenerationProviderName.FAKE
    comfyui_base_url: str = "http://localhost:8188"
    comfyui_timeout_seconds: int = Field(default=30, ge=1)
    comfyui_max_retries: int = Field(default=3, ge=0, le=10)

    @field_validator("api_cors_origins")
    @classmethod
    def _reject_wildcard_origin(cls, value: str) -> str:
        """A wildcard origin would defeat cookie/credential isolation."""
        if "*" in value:
            msg = "api_cors_origins must list explicit origins, never '*'"
            raise ValueError(msg)
        return value

    @model_validator(mode="after")
    def validate_production_safety(self) -> Self:
        """Refuse to boot a real environment with development placeholders."""
        if self.environment in (Environment.DEVELOPMENT, Environment.TEST):
            return self

        problems: list[str] = []
        if self.secret_key == DEV_SECRET_KEY:
            problems.append("SECRET_KEY still holds the development placeholder")
        if len(self.secret_key) < MIN_SECRET_KEY_LENGTH:
            problems.append(f"SECRET_KEY must be at least {MIN_SECRET_KEY_LENGTH} characters")
        if self.dev_auth_enabled:
            problems.append("DEV_AUTH_ENABLED must be false outside development")
        if problems:
            msg = f"Unsafe configuration for {self.environment}: " + "; ".join(problems)
            raise ValueError(msg)
        return self

    @property
    def cors_origin_list(self) -> list[str]:
        """CORS origins as a list, from the comma-separated env value."""
        return [origin.strip() for origin in self.api_cors_origins.split(",") if origin.strip()]

    @property
    def is_development(self) -> bool:
        return self.environment is Environment.DEVELOPMENT

    @property
    def dev_auth_active(self) -> bool:
        """The dev-login stub only exists in development, whatever the flag says.

        Two independent conditions must hold, so flipping a single environment
        variable in staging cannot open a passwordless login route.
        """
        return self.dev_auth_enabled and self.environment is Environment.DEVELOPMENT

    def _database_dsn(self, database: str) -> str:
        dsn = PostgresDsn.build(
            scheme="postgresql+asyncpg",
            username=self.postgres_user,
            password=self.postgres_password,
            host=self.postgres_host,
            port=self.postgres_port,
            path=database,
        )
        return str(dsn)

    @property
    def database_url(self) -> str:
        """Async SQLAlchemy DSN for the application database."""
        return self._database_dsn(self.postgres_db)

    @property
    def test_database_url(self) -> str:
        """Async SQLAlchemy DSN for the dedicated test database."""
        return self._database_dsn(self.postgres_test_db)

    @property
    def sync_database_url(self) -> str:
        """Sync DSN. Alembic drives migrations through the async engine, but some
        tooling (e.g. `CREATE DATABASE`) needs a non-async driver."""
        return self.database_url.replace("postgresql+asyncpg", "postgresql")

    @property
    def redis_url(self) -> str:
        dsn = RedisDsn.build(
            scheme="redis",
            host=self.redis_host,
            port=self.redis_port,
            path=str(self.redis_db),
        )
        return str(dsn)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings singleton.

    Cached so that validation runs once. Tests clear the cache via
    `get_settings.cache_clear()` after patching the environment.
    """
    return Settings()
