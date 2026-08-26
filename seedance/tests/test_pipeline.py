from __future__ import annotations

import pytest

from seedance.ledger import Ledger
from seedance.models import JobKind, JobRecord, JobSpec, Resolution
from seedance.pipeline import (
    PipelineError,
    draft_specs,
    final_spec,
    pick_draft,
    plan,
    run_drafts,
)
from seedance.pricing import RateTable
from seedance.runner import Runner


def test_drafts_differ_only_by_seed() -> None:
    specs = draft_specs(
        "a prompt", variants=3, resolution=Resolution.R480P, duration_s=5, seed_base=1000
    )
    assert [spec.seed for spec in specs] == [1000, 1001, 1002]
    assert {spec.prompt for spec in specs} == {"a prompt"}


def test_a_run_must_have_at_least_one_variant() -> None:
    with pytest.raises(PipelineError, match="at least one"):
        draft_specs("x", variants=0, resolution=Resolution.R480P, duration_s=5, seed_base=1)


def test_the_plan_totals_before_anything_is_spent(rates: RateTable) -> None:
    specs = draft_specs("x", variants=3, resolution=Resolution.R480P, duration_s=5, seed_base=1)
    assert plan(rates, "modelark", specs).total_usd == pytest.approx(3 * 0.514, abs=0.005)


def test_drafting_cheap_then_finishing_once_is_the_cheaper_path(rates: RateTable) -> None:
    """The claim the whole tool is built on, checked against the rate table."""
    draft = rates.estimate("modelark", JobSpec(prompt="x", resolution=Resolution.R480P)).usd
    final = rates.estimate("modelark", JobSpec(prompt="x", resolution=Resolution.R720P)).usd

    staged = 3 * draft + final
    all_at_720 = 4 * final

    assert staged == pytest.approx(2.70, abs=0.02)
    assert all_at_720 == pytest.approx(4.62, abs=0.02)
    assert staged < all_at_720 * 0.6


async def test_promoting_a_draft_keeps_prompt_and_seed(runner: Runner, ledger: Ledger) -> None:
    specs = draft_specs(
        "a cinematic push-in",
        variants=3,
        resolution=Resolution.R480P,
        duration_s=5,
        seed_base=500,
    )
    drafts = await run_drafts(runner, specs)

    chosen = pick_draft(drafts, index=2, seed=None)
    promoted = final_spec(chosen, resolution=Resolution.R720P)

    assert promoted.seed == 501
    assert promoted.prompt == "a cinematic push-in"
    assert promoted.resolution is Resolution.R720P
    assert ledger.by_run(drafts[0].run_id)[0].kind is JobKind.DRAFT


async def test_a_draft_can_be_chosen_by_seed(runner: Runner) -> None:
    drafts = await run_drafts(
        runner,
        draft_specs("x", variants=3, resolution=Resolution.R480P, duration_s=5, seed_base=7),
    )
    assert pick_draft(drafts, index=None, seed=8).spec.seed == 8


def test_picking_reports_what_is_available() -> None:
    spec = JobSpec(prompt="x", seed=1)
    drafts = [
        JobRecord(
            id="a",
            run_id="r",
            kind=JobKind.DRAFT,
            provider="fake",
            spec=spec,
            fingerprint="f",
            video_path="/tmp/a.mp4",  # noqa: S108 - a fixture path, never opened
        )
    ]
    with pytest.raises(PipelineError, match="have: 1"):
        pick_draft(drafts, index=None, seed=99)
    with pytest.raises(PipelineError, match=r"--pick must be 1\.\.1"):
        pick_draft(drafts, index=5, seed=None)
    with pytest.raises(PipelineError, match="say which draft"):
        pick_draft(drafts, index=None, seed=None)


def test_a_run_with_no_finished_draft_cannot_be_promoted() -> None:
    with pytest.raises(PipelineError, match="no finished draft"):
        pick_draft([], index=1, seed=None)
