"""The queue, end to end, against the offline provider."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from seedance import runner as runner_module
from seedance.config import Settings
from seedance.ledger import BudgetExceededError, Ledger
from seedance.models import JobKind, JobSpec, JobStatus, Resolution
from seedance.providers.fake import FakeProvider
from seedance.runner import Runner


@pytest.fixture(autouse=True)
def _no_backoff_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runner_module, "_backoff_delay", lambda _attempt: 0.0)


def _specs(count: int) -> list[JobSpec]:
    return [JobSpec(prompt="a test clip", seed=100 + index) for index in range(count)]


async def test_a_run_produces_files_and_a_paper_trail(runner: Runner, ledger: Ledger) -> None:
    jobs = await runner.run_all(_specs(3), kind=JobKind.DRAFT)

    assert [job.status for job in jobs] == [JobStatus.SUCCEEDED] * 3
    for job in jobs:
        assert job.video_path is not None
        assert Path(job.video_path).exists()

    assert len(ledger.recent()) == 3
    assert ledger.today_spend() == pytest.approx(sum(job.billed_usd for job in jobs))


async def test_every_job_is_costed_before_it_is_sent(runner: Runner) -> None:
    jobs = await runner.run_all(_specs(1))
    # 5 s of 480p on the direct rate.
    assert jobs[0].estimated_usd == pytest.approx(0.514, abs=0.001)


async def test_the_same_job_twice_is_paid_for_once(
    runner: Runner, fake_provider: FakeProvider
) -> None:
    first = await runner.run_all(_specs(2))
    second = await runner.run_all(_specs(2))

    assert len(fake_provider.submitted) == 2, "the second run must not reach the provider"
    assert all(job.cached for job in second)
    assert all(job.billed_usd == 0.0 for job in second)
    assert [job.video_path for job in second] == [job.video_path for job in first]


async def test_no_cache_forces_a_fresh_generation(
    runner: Runner, fake_provider: FakeProvider
) -> None:
    await runner.run_all(_specs(1))
    await runner.run_all(_specs(1), use_cache=False)
    assert len(fake_provider.submitted) == 2


async def test_a_different_resolution_is_a_different_job(
    runner: Runner, fake_provider: FakeProvider
) -> None:
    await runner.run_all(_specs(1))
    await runner.run_all([_specs(1)[0].with_(resolution=Resolution.R720P)])
    assert len(fake_provider.submitted) == 2


async def test_the_cap_blocks_the_run(runner: Runner, ledger: Ledger) -> None:
    ledger.set_cap("daily", 1.0)
    with pytest.raises(BudgetExceededError, match="daily budget"):
        await runner.run_all(_specs(3))


async def test_the_cap_holds_under_concurrency(
    settings: Settings, runner: Runner, ledger: Ledger, fake_provider: FakeProvider
) -> None:
    """Eight parallel submissions must not each see the same "spent so far"."""
    ledger.set_cap("daily", 1.2)  # room for exactly two 480p jobs
    assert settings.concurrency > 1

    with pytest.raises(BudgetExceededError):
        await runner.run_all(_specs(8))

    assert len(fake_provider.submitted) <= 2


async def test_force_overrides_the_cap(runner: Runner, ledger: Ledger) -> None:
    ledger.set_cap("daily", 0.01)
    jobs = await runner.run_all(_specs(1), force=True)
    assert jobs[0].status is JobStatus.SUCCEEDED


async def test_a_transient_failure_is_retried(runner: Runner, fake_provider: FakeProvider) -> None:
    fake_provider.fail_first_n = 2
    jobs = await runner.run_all(_specs(1))
    assert jobs[0].status is JobStatus.SUCCEEDED


async def test_giving_up_records_the_failure_instead_of_raising(
    runner: Runner, fake_provider: FakeProvider, ledger: Ledger
) -> None:
    fake_provider.fail_first_n = 99
    jobs = await runner.run_all(_specs(1))

    assert jobs[0].status is JobStatus.FAILED
    assert jobs[0].error is not None
    # A failed job is not billed, so it must not eat the budget.
    assert ledger.today_spend() == pytest.approx(0.0)


async def test_concurrency_is_bounded(settings: Settings, runner: Runner) -> None:
    in_flight = 0
    peak = 0
    original = runner.provider.submit

    async def counting_submit(client: object, spec: JobSpec) -> str:
        nonlocal in_flight, peak
        in_flight += 1
        peak = max(peak, in_flight)
        try:
            await asyncio.sleep(0)
            return await original(client, spec)  # type: ignore[arg-type]
        finally:
            in_flight -= 1

    runner.provider.submit = counting_submit  # type: ignore[method-assign]
    await runner.run_all(_specs(12))
    assert peak <= settings.concurrency
