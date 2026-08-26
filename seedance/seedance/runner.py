"""The queue.

Submits jobs at a bounded concurrency, polls each to completion, downloads the
result and keeps the ledger straight. Three things here exist because of how
this particular API behaves:

* **Concurrency, not request rate, is the constraint.** One Seedance job holds a
  GPU for minutes, and no provider publishes a ceiling. So the runner caps
  in-flight jobs and treats 429 as the signal to back off, not as an error.
* **The budget check is serialised.** Costing a job, checking it against the cap
  and writing it to the ledger happen under one lock; otherwise eight concurrent
  submissions each see the same "spent so far" and sail past the cap together.
* **The estimate is replaced by the real number where there is one.** ModelArk
  returns `usage.completion_tokens`; when it does, the ledger records what was
  actually charged rather than what was predicted.
"""

from __future__ import annotations

import asyncio
import random
import shutil
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import unquote, urlparse
from uuid import uuid4

import httpx

from seedance.config import Settings
from seedance.ledger import Ledger
from seedance.models import JobKind, JobRecord, JobSpec, JobStatus
from seedance.pricing import RateTable
from seedance.providers import Provider, RetryableProviderError

BACKOFF_BASE_S = 2.0
BACKOFF_CAP_S = 60.0

EventHook = Callable[[str], None]


def _silent(_message: str) -> None:
    """Default event hook — the CLI swaps in one that prints."""


class JobTimeoutError(RuntimeError):
    def __init__(self, job_id: str, seconds: float) -> None:
        super().__init__(f"job {job_id} did not finish within {seconds:.0f}s")


def new_run_id() -> str:
    return f"{datetime.now(UTC):%Y%m%d-%H%M%S}-{uuid4().hex[:4]}"


def _backoff_delay(attempt: int) -> float:
    """Exponential backoff with jitter, so retries do not resynchronise."""
    ceiling = min(BACKOFF_BASE_S * 2.0**attempt, BACKOFF_CAP_S)
    # Jitter only; nothing here is security-sensitive.
    return ceiling * (0.5 + random.random() / 2)  # noqa: S311


@dataclass(frozen=True, slots=True)
class RunOptions:
    """The two switches that ride along with every submission.

    `force` skips the budget check; `use_cache` decides whether an identical
    finished job may be served from disk instead of paid for again.
    """

    force: bool = False
    use_cache: bool = True


@dataclass(slots=True)
class Runner:
    settings: Settings
    rates: RateTable
    ledger: Ledger
    provider: Provider
    on_event: EventHook = _silent
    _budget_lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)

    # -- one job ------------------------------------------------------------

    async def _reserve(
        self, spec: JobSpec, run_id: str, kind: JobKind, options: RunOptions
    ) -> JobRecord:
        """Cost the job, check the cap and claim the spend — all under one lock."""
        fingerprint = spec.fingerprint(self.provider.name)

        async with self._budget_lock:
            if options.use_cache:
                hit = self.ledger.find_completed(fingerprint)
                if hit is not None:
                    self.on_event(f"cache hit, not paying again: {hit.video_path}")
                    return self.ledger.record(
                        JobRecord(
                            id=uuid4().hex[:12],
                            run_id=run_id,
                            kind=kind,
                            provider=self.provider.name,
                            spec=spec,
                            fingerprint=fingerprint,
                            status=JobStatus.SUCCEEDED,
                            estimated_usd=0.0,
                            actual_usd=0.0,
                            video_path=hit.video_path,
                            cached=True,
                        )
                    )

            estimate = self.rates.estimate(self.provider.rate_key, spec)
            if not options.force:
                self.ledger.assert_within_budget(
                    estimate.usd,
                    daily=self.settings.daily_budget_usd,
                    monthly=self.settings.monthly_budget_usd,
                )
            return self.ledger.record(
                JobRecord(
                    id=uuid4().hex[:12],
                    run_id=run_id,
                    kind=kind,
                    provider=self.provider.name,
                    spec=spec,
                    fingerprint=fingerprint,
                    status=JobStatus.PENDING,
                    estimated_usd=estimate.usd,
                    tokens=estimate.tokens,
                )
            )

    async def _submit_with_retry(self, client: httpx.AsyncClient, spec: JobSpec) -> str:
        last: Exception | None = None
        for attempt in range(self.settings.max_retries):
            try:
                return await self.provider.submit(client, spec)
            except (RetryableProviderError, httpx.TransportError) as exc:
                last = exc
                delay = _backoff_delay(attempt)
                self.on_event(f"retrying in {delay:.1f}s after: {exc}")
                await asyncio.sleep(delay)
        raise RetryableProviderError(f"gave up after {self.settings.max_retries} attempts: {last}")

    async def _await_result(self, client: httpx.AsyncClient, job: JobRecord) -> JobRecord:
        deadline = asyncio.get_running_loop().time() + self.settings.job_timeout_s
        assert job.provider_task_id is not None  # noqa: S101 - set by the caller

        while True:
            if asyncio.get_running_loop().time() > deadline:
                raise JobTimeoutError(job.id, self.settings.job_timeout_s)

            status = await self.provider.poll(client, job.provider_task_id)

            if status.status is JobStatus.FAILED:
                job.status = JobStatus.FAILED
                job.error = status.error or "provider reported failure"
                return self.ledger.record(job)

            if status.status is JobStatus.SUCCEEDED:
                if not status.video_url:
                    job.status = JobStatus.FAILED
                    job.error = "provider reported success without a video url"
                    return self.ledger.record(job)

                job.video_path = str(await self._download(client, status.video_url, job))
                job.status = JobStatus.SUCCEEDED
                if status.tokens:
                    # Bill against what was charged, not what was predicted.
                    job.tokens = status.tokens
                    rates = self.rates.provider(self.provider.rate_key)
                    rate = rates.token_rate(
                        job.spec.resolution, with_video=job.spec.has_video_input
                    )
                    job.actual_usd = status.tokens * rate / 1_000_000
                return self.ledger.record(job)

            if job.status is not JobStatus.RUNNING:
                job.status = JobStatus.RUNNING
                self.ledger.record(job)
            await asyncio.sleep(self.settings.poll_interval_s)

    async def _download(self, client: httpx.AsyncClient, url: str, job: JobRecord) -> Path:
        target_dir = self.settings.output_dir / job.run_id
        target_dir.mkdir(parents=True, exist_ok=True)
        suffix = "" if job.spec.seed is None else f"-seed{job.spec.seed}"
        target = target_dir / f"{job.kind.value}-{job.id}{suffix}.mp4"

        parsed = urlparse(url)
        if parsed.scheme == "file":
            shutil.copyfile(unquote(parsed.path), target)
            return target

        async with client.stream("GET", url) as response:
            response.raise_for_status()
            with target.open("wb") as handle:
                async for chunk in response.aiter_bytes():
                    handle.write(chunk)
        return target

    async def run_one(
        self,
        client: httpx.AsyncClient,
        spec: JobSpec,
        *,
        run_id: str,
        kind: JobKind,
        options: RunOptions = RunOptions(),
    ) -> JobRecord:
        job = await self._reserve(spec, run_id, kind, options)
        if job.cached:
            return job

        try:
            job.provider_task_id = await self._submit_with_retry(client, spec)
            self.ledger.record(job)
            self.on_event(f"submitted {job.id} -> {job.provider_task_id}")
            return await self._await_result(client, job)
        except Exception as exc:  # noqa: BLE001 - recorded, then handed back to the caller
            job.status = JobStatus.FAILED
            job.error = str(exc)
            self.on_event(f"job {job.id} failed: {exc}")
            return self.ledger.record(job)

    # -- many jobs ----------------------------------------------------------

    async def run_all(
        self,
        specs: Sequence[JobSpec],
        *,
        run_id: str | None = None,
        kind: JobKind = JobKind.ONE_OFF,
        force: bool = False,
        use_cache: bool = True,
    ) -> list[JobRecord]:
        options = RunOptions(force=force, use_cache=use_cache)
        run_id = run_id or new_run_id()
        semaphore = asyncio.Semaphore(self.settings.concurrency)

        async with httpx.AsyncClient(timeout=60.0) as client:

            async def guarded(spec: JobSpec) -> JobRecord:
                async with semaphore:
                    return await self.run_one(
                        client, spec, run_id=run_id, kind=kind, options=options
                    )

            return list(await asyncio.gather(*(guarded(spec) for spec in specs)))
