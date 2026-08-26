from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from seedance.ledger import BudgetExceededError, Ledger
from seedance.models import JobKind, JobRecord, JobSpec, JobStatus


def _job(
    ledger: Ledger,
    *,
    job_id: str = "j1",
    status: JobStatus = JobStatus.SUCCEEDED,
    usd: float = 1.0,
    actual: float | None = None,
    run_id: str = "run-1",
    video: Path | None = None,
    cached: bool = False,
) -> JobRecord:
    spec = JobSpec(prompt="x", seed=1)
    return ledger.record(
        JobRecord(
            id=job_id,
            run_id=run_id,
            kind=JobKind.DRAFT,
            provider="fake",
            spec=spec,
            fingerprint=spec.fingerprint("fake"),
            status=status,
            estimated_usd=usd,
            actual_usd=actual,
            video_path=str(video) if video else None,
            cached=cached,
        )
    )


def test_round_trips_a_job(ledger: Ledger) -> None:
    stored = _job(ledger)
    loaded = ledger.get(stored.id)
    assert loaded is not None
    assert loaded.spec == stored.spec
    assert loaded.status is JobStatus.SUCCEEDED


def test_record_is_an_upsert(ledger: Ledger) -> None:
    job = _job(ledger, status=JobStatus.PENDING)
    job.status = JobStatus.SUCCEEDED
    job.actual_usd = 0.42
    ledger.record(job)

    loaded = ledger.get(job.id)
    assert loaded is not None
    assert loaded.actual_usd == 0.42
    assert len(ledger.recent()) == 1


def test_actual_spend_wins_over_the_estimate(ledger: Ledger) -> None:
    job = _job(ledger, usd=1.0, actual=0.7)
    assert job.billed_usd == 0.7


def test_cache_lookup_needs_the_file_to_still_exist(ledger: Ledger, tmp_path: Path) -> None:
    spec = JobSpec(prompt="x", seed=1)
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"data")
    _job(ledger, video=video)

    assert ledger.find_completed(spec.fingerprint("fake")) is not None

    video.unlink()
    assert ledger.find_completed(spec.fingerprint("fake")) is None


def test_failed_and_cached_jobs_do_not_consume_budget(ledger: Ledger) -> None:
    _job(ledger, job_id="ok", usd=2.0)
    _job(ledger, job_id="failed", usd=5.0, status=JobStatus.FAILED)
    _job(ledger, job_id="from-cache", usd=5.0, cached=True)

    assert ledger.today_spend() == pytest.approx(2.0)


def test_pending_jobs_do_consume_budget(ledger: Ledger) -> None:
    """Money that might still land has to count, or concurrency beats the cap."""
    _job(ledger, job_id="pending", usd=3.0, status=JobStatus.PENDING)
    assert ledger.today_spend() == pytest.approx(3.0)


def test_spend_window_excludes_older_jobs(ledger: Ledger) -> None:
    _job(ledger, usd=2.0)
    tomorrow = datetime.now(UTC) + timedelta(days=1)
    assert ledger.spend_since(tomorrow) == pytest.approx(0.0)


def test_budget_blocks_the_submission_that_would_cross_the_cap(ledger: Ledger) -> None:
    _job(ledger, usd=9.0)
    ledger.set_cap("daily", 10.0)

    ledger.assert_within_budget(0.5, daily=0.0, monthly=0.0)
    with pytest.raises(BudgetExceededError, match="daily budget"):
        ledger.assert_within_budget(2.0, daily=0.0, monthly=0.0)


def test_stored_cap_overrides_the_environment_default(ledger: Ledger) -> None:
    _job(ledger, usd=9.0)
    ledger.set_cap("monthly", 100.0)
    ledger.assert_within_budget(5.0, daily=0.0, monthly=10.0)


def test_zero_cap_means_no_cap(ledger: Ledger) -> None:
    _job(ledger, usd=1000.0)
    ledger.assert_within_budget(1000.0, daily=0.0, monthly=0.0)


def test_runs_are_listed_in_order(ledger: Ledger) -> None:
    _job(ledger, job_id="a", run_id="run-a")
    _job(ledger, job_id="b", run_id="run-b")
    assert ledger.latest_run_id(JobKind.DRAFT) in {"run-a", "run-b"}
    assert [job.id for job in ledger.by_run("run-a")] == ["a"]
