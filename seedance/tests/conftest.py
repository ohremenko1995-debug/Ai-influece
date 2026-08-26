from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from seedance.config import Settings, isolated_settings
from seedance.ledger import Ledger
from seedance.pricing import RateTable, load_rates
from seedance.providers.fake import FakeProvider
from seedance.runner import Runner


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return isolated_settings(
        output_dir=tmp_path / "out",
        db_path=tmp_path / "seedance.db",
        concurrency=4,
        poll_interval_s=0.0,
        job_timeout_s=5.0,
        max_retries=3,
        modelark_api_key="ark-test-key",
        replicate_api_token="r8-test-token",
        wavespeed_api_key="ws-test-key",
    )


@pytest.fixture
def rates() -> RateTable:
    return load_rates()


@pytest.fixture
def ledger(settings: Settings) -> Iterator[Ledger]:
    store = Ledger(settings.db_path)
    yield store
    store.close()


@pytest.fixture
def fake_provider(settings: Settings) -> FakeProvider:
    return FakeProvider(settings)


@pytest.fixture
def runner(
    settings: Settings, rates: RateTable, ledger: Ledger, fake_provider: FakeProvider
) -> Runner:
    return Runner(settings=settings, rates=rates, ledger=ledger, provider=fake_provider)
