"""The draft-then-final workflow.

This is where the money is saved. Seedance charges by pixels x seconds, so the
same footage costs 2.25x more at 720p than at 480p and another 2.5x at 1080p,
while duration is strictly linear. The cheap way to arrive at one good clip is
therefore not a cheaper provider — it is fewer expensive takes:

    draft   N seeds at 480p        -> look at them, pick one
    final   that one seed at 720p  -> pay the resolution once

Three 480p drafts plus one 720p final on the direct channel is about $2.70 per
finished 5-second clip. Four takes straight to 720p is $4.62 for the same work.
The seed carries over, so the final is the draft you approved, at the resolution
you want it.
"""

from __future__ import annotations

from dataclasses import dataclass

from seedance.models import CostEstimate, JobKind, JobRecord, JobSpec, Resolution
from seedance.pricing import RateTable
from seedance.runner import Runner, new_run_id


class PipelineError(RuntimeError):
    """Raised when a run cannot be continued as asked."""


@dataclass(frozen=True, slots=True)
class RunPlan:
    """What a command is about to spend, before it spends it."""

    specs: tuple[JobSpec, ...]
    provider: str
    per_job: tuple[CostEstimate, ...]

    @property
    def total_usd(self) -> float:
        return sum(estimate.usd for estimate in self.per_job)


def plan(rates: RateTable, provider_rate_key: str, specs: list[JobSpec]) -> RunPlan:
    """Cost a set of jobs without submitting anything."""
    return RunPlan(
        specs=tuple(specs),
        provider=provider_rate_key,
        per_job=tuple(rates.estimate(provider_rate_key, spec) for spec in specs),
    )


def draft_specs(
    prompt: str,
    *,
    variants: int,
    resolution: Resolution,
    duration_s: int,
    seed_base: int,
    **overrides: object,
) -> list[JobSpec]:
    """One spec per seed — same prompt, different draw."""
    if variants < 1:
        raise PipelineError("need at least one variant")
    return [
        JobSpec(
            prompt=prompt,
            resolution=resolution,
            duration_s=duration_s,
            seed=seed_base + index,
            **overrides,  # type: ignore[arg-type]
        )
        for index in range(variants)
    ]


async def run_drafts(
    runner: Runner, specs: list[JobSpec], *, force: bool = False
) -> list[JobRecord]:
    return await runner.run_all(specs, run_id=new_run_id(), kind=JobKind.DRAFT, force=force)


def pick_draft(drafts: list[JobRecord], *, index: int | None, seed: int | None) -> JobRecord:
    """Find the draft to promote, by 1-based position or by seed."""
    succeeded = [job for job in drafts if job.video_path]
    if not succeeded:
        raise PipelineError("that run has no finished draft to promote")

    if seed is not None:
        for job in succeeded:
            if job.spec.seed == seed:
                return job
        available = ", ".join(str(job.spec.seed) for job in succeeded)
        raise PipelineError(f"no draft with seed {seed} in this run; have: {available}")

    if index is None:
        raise PipelineError("say which draft to promote: --pick <n> or --seed <n>")
    if not 1 <= index <= len(succeeded):
        raise PipelineError(f"--pick must be 1..{len(succeeded)} for this run")
    return succeeded[index - 1]


def final_spec(
    draft: JobRecord, *, resolution: Resolution, duration_s: int | None = None
) -> JobSpec:
    """The approved draft, at final resolution, same seed and prompt."""
    changes: dict[str, object] = {"resolution": resolution}
    if duration_s is not None:
        changes["duration_s"] = duration_s
    return draft.spec.with_(**changes)


async def run_final(
    runner: Runner, spec: JobSpec, *, run_id: str, force: bool = False
) -> JobRecord:
    records = await runner.run_all([spec], run_id=run_id, kind=JobKind.FINAL, force=force)
    return records[0]
