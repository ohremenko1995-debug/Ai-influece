"""Runtime settings.

Read from the environment (prefix `SEEDANCE_`) or a local `.env`. Provider
credentials are the exception — they keep the names the providers themselves
document, so an existing key in your shell works without renaming.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from seedance.models import Resolution


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="SEEDANCE_",
        extra="ignore",
        # Credentials validate from the providers' own env names; this keeps the
        # Python field names working too, for tests and programmatic callers.
        populate_by_name=True,
    )

    # --- where things land -------------------------------------------------
    output_dir: Path = Path("./out")
    db_path: Path = Path("./seedance.db")

    # --- the draft/final pipeline -----------------------------------------
    # Drafts run at 480p because 480p -> 720p is a 2.25x jump in tokens for the
    # same footage: iterate cheap, pay for the resolution only on the take you keep.
    draft_provider: str = "modelark"
    draft_resolution: Resolution = Resolution.R480P
    final_provider: str = "modelark"
    final_resolution: Resolution = Resolution.R720P

    # --- runner ------------------------------------------------------------
    # No provider publishes a concurrency ceiling for Seedance 2.5, and a single
    # job holds a GPU for minutes, so in-flight jobs are the binding constraint.
    # 8 is a conservative start; raise it once 429s tell you where the wall is.
    concurrency: int = 8
    poll_interval_s: float = 5.0
    job_timeout_s: float = 900.0
    max_retries: int = 4

    # --- spend caps --------------------------------------------------------
    # Zero means "no cap set". A cap stored via `seedance budget` overrides these.
    daily_budget_usd: float = 0.0
    monthly_budget_usd: float = 0.0

    # --- credentials -------------------------------------------------------
    # `validation_alias` rather than `alias`: the environment uses the name each
    # provider documents, while the field keeps its Python name for callers.
    modelark_api_key: str = Field(default="", validation_alias="ARK_API_KEY")
    modelark_base_url: str = Field(
        default="https://ark.ap-southeast.bytepluses.com/api/v3",
        validation_alias="ARK_BASE_URL",
    )
    replicate_api_token: str = Field(default="", validation_alias="REPLICATE_API_TOKEN")
    wavespeed_api_key: str = Field(default="", validation_alias="WAVESPEED_API_KEY")


def load_settings() -> Settings:
    return Settings()


def isolated_settings(**overrides: Any) -> Settings:
    """Settings from explicit values, ignoring any local `.env`.

    The test suite builds settings this way so that a developer's own `.env`
    cannot change what a test asserts.
    """
    # pydantic-settings accepts `_env_file` at runtime; the synthesised
    # __init__ mypy sees does not carry it.
    return Settings(_env_file=None, **overrides)  # type: ignore[call-arg]
