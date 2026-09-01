"""The domain rules that everything else assumes hold."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from identitylock.domain.models import (
    CandidateMetrics,
    Character,
    FrameStats,
    LoraRef,
    PromptSpec,
    Recipe,
    RunAggregates,
    Suite,
    content_hash,
)
from identitylock.domain.policy import (
    ComparisonPolicy,
    Policy,
    evaluate_candidate,
    evaluate_comparison,
    evaluate_run,
)


def _metrics(**overrides: float | None) -> CandidateMetrics:
    base: dict[str, object] = {
        "identity_similarity": 0.8,
        "nearest_reference": 0.85,
        "identity_margin": 0.3,
        "impostor_best": 0.5,
        "impostor_id": "other",
        "technical_score": 0.7,
        "frame": FrameStats(
            width=64,
            height=64,
            sharpness=0.7,
            exposure=0.9,
            contrast=0.6,
            colorfulness=0.4,
            clipping=0.0,
            entropy=0.8,
        ),
    }
    base.update(overrides)
    return CandidateMetrics.model_validate(base)


def _aggregates(**overrides: float | None) -> RunAggregates:
    base: dict[str, object] = {
        "n_total": 10,
        "n_accepted": 10,
        "identity_mean": 0.8,
        "identity_std": 0.05,
        "identity_p05": 0.7,
        "identity_min": 0.65,
        "identity_max": 0.9,
        "margin_mean": 0.3,
        "technical_mean": 0.7,
        "consistency_rate": 1.0,
        "diversity": 0.2,
        "drift_slope": 0.0,
        "drift_r2": 0.0,
        "drift_p_value": 1.0,
        "identity_ci_low": 0.75,
        "identity_ci_high": 0.85,
    }
    base.update(overrides)
    return RunAggregates.model_validate(base)


class TestContentHash:
    def test_is_order_independent(self) -> None:
        assert content_hash({"a": 1, "b": 2}) == content_hash({"b": 2, "a": 1})

    def test_separates_different_values(self) -> None:
        assert content_hash({"a": 1}) != content_hash({"a": 2})


class TestRecipeRevision:
    def test_explicit_default_hashes_like_an_omitted_one(self) -> None:
        assert Recipe(id="r", name="R", steps=8).revision == Recipe(id="r", name="R").revision

    def test_generation_fields_change_it(self) -> None:
        assert Recipe(id="r", name="R", steps=9).revision != Recipe(id="r", name="R").revision

    def test_labels_do_not_change_it(self) -> None:
        assert Recipe(id="x", name="Other").revision == Recipe(id="r", name="R").revision

    def test_loras_change_it(self) -> None:
        with_lora = Recipe(id="r", name="R", loras=(LoraRef(name="a", weight=0.5),))
        assert with_lora.revision != Recipe(id="r", name="R").revision

    def test_a_supplied_revision_is_recomputed(self) -> None:
        """A report cannot claim a revision its own fields do not produce."""
        forged = Recipe(id="r", name="R", revision="deadbeef")
        assert forged.revision == Recipe(id="r", name="R").revision

    def test_round_trips_through_json(self) -> None:
        recipe = Recipe(id="r", name="R", steps=12, cfg=3.5)
        assert Recipe.model_validate(recipe.model_dump(mode="json")) == recipe


class TestModelsAreFrozen:
    def test_recipe_rejects_mutation(self) -> None:
        recipe = Recipe(id="r", name="R")
        with pytest.raises(ValidationError):
            recipe.steps = 20

    def test_unknown_fields_are_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Recipe.model_validate({"id": "r", "name": "R", "nonsense": 1})


class TestSuitePlan:
    def _suite(self) -> Suite:
        return Suite(
            id="s",
            character=Character(id="c", name="C"),
            prompts=(PromptSpec(id="a", text="a"), PromptSpec(id="b", text="b")),
            seeds=(1, 2, 3),
            recipe=Recipe(id="r", name="R"),
        )

    def test_covers_the_whole_grid(self) -> None:
        assert len(self._suite().plan) == 6

    def test_is_seed_major_so_prompts_interleave(self) -> None:
        """Prompt difficulty must not be aliased with position in the batch."""
        prompts = [prompt.id for prompt, _ in self._suite().plan]
        assert prompts == ["a", "b", "a", "b", "a", "b"]

    def test_is_deterministic(self) -> None:
        assert self._suite().plan == self._suite().plan


class TestCandidateGate:
    def test_accepts_a_good_frame(self) -> None:
        decision, reasons = evaluate_candidate(_metrics(), Policy())
        assert decision == "accept"
        assert reasons == ()

    def test_rejects_on_identity(self) -> None:
        decision, reasons = evaluate_candidate(_metrics(identity_similarity=0.0), Policy())
        assert decision == "reject"
        assert any("identity" in reason for reason in reasons)

    def test_rejects_on_margin(self) -> None:
        _, reasons = evaluate_candidate(_metrics(identity_margin=0.0), Policy())
        assert any("margin" in reason for reason in reasons)

    def test_missing_margin_is_skipped_not_failed(self) -> None:
        """A cohort of one cannot produce a margin; that is not a rejection."""
        decision, reasons = evaluate_candidate(
            _metrics(identity_margin=None, impostor_best=None), Policy()
        )
        assert decision == "accept"
        assert reasons == ()

    def test_collects_every_reason(self) -> None:
        _, reasons = evaluate_candidate(
            _metrics(identity_similarity=0.0, technical_score=0.0), Policy()
        )
        assert len(reasons) == 2


class TestRunGate:
    def test_passes_a_clean_run(self) -> None:
        assert evaluate_run(_aggregates(), Policy()).passed

    def test_names_the_gate_that_failed(self) -> None:
        verdict = evaluate_run(_aggregates(consistency_rate=0.1), Policy())
        assert not verdict.passed
        assert verdict.failed_gates == ("consistency_rate",)

    def test_large_drift_needs_significance_too(self) -> None:
        """Magnitude alone must not fail a batch, and neither must significance."""
        loud_but_random = _aggregates(drift_slope=-0.9, drift_p_value=0.9)
        assert evaluate_run(loud_but_random, Policy()).passed

        tiny_but_significant = _aggregates(drift_slope=-0.001, drift_p_value=0.0001)
        assert evaluate_run(tiny_but_significant, Policy()).passed

        real_drift = _aggregates(drift_slope=-0.9, drift_p_value=0.0001)
        assert not evaluate_run(real_drift, Policy()).passed


class TestComparisonVerdict:
    def _verdict(self, **kwargs: float) -> str:
        payload: dict[str, float] = {
            "win_rate": 0.8,
            "mean_delta": 0.1,
            "ci_low": 0.05,
            "ci_high": 0.15,
            "effect_size": 0.6,
            "n_pairs": 20,
        }
        payload.update(kwargs)
        return evaluate_comparison(policy=ComparisonPolicy(), **payload).outcome  # type: ignore[arg-type]

    def test_clear_win_is_an_improvement(self) -> None:
        assert self._verdict() == "improvement"

    def test_interval_across_zero_is_inconclusive(self) -> None:
        assert self._verdict(ci_low=-0.02, ci_high=0.2) == "inconclusive"

    def test_interval_below_zero_is_a_regression(self) -> None:
        assert self._verdict(mean_delta=-0.1, ci_low=-0.2, ci_high=-0.05) == "regression"

    def test_a_win_rate_below_the_bar_is_inconclusive(self) -> None:
        assert self._verdict(win_rate=0.5) == "inconclusive"

    def test_a_negligible_effect_is_inconclusive(self) -> None:
        assert self._verdict(effect_size=0.01) == "inconclusive"


class TestPolicyFingerprint:
    def test_is_stable(self) -> None:
        assert Policy().fingerprint() == Policy().fingerprint()

    def test_changes_with_any_threshold(self) -> None:
        assert Policy().fingerprint() != Policy(identity_min=0.9).fingerprint()


class TestThresholdModelsLiveInTheDomain:
    """The threshold values are domain data; the rules that apply them are not.

    `RunManifest` has to carry the policy a run was judged under, which it cannot
    do if `Policy` lives in the module that imports `RunManifest`. Both import
    paths resolve to the same class so nothing downstream had to change.
    """

    def test_policy_is_importable_from_both_places(self) -> None:
        from identitylock.domain.models import ComparisonPolicy as ModelsComparisonPolicy
        from identitylock.domain.models import Policy as ModelsPolicy

        assert ModelsPolicy is Policy
        assert ModelsComparisonPolicy is ComparisonPolicy


class TestTooFewPairs:
    """A bootstrap over one cell resamples the same number and returns no width."""

    def _verdict(self, n_pairs: int, **kwargs: float) -> str:
        payload: dict[str, float] = {
            "win_rate": 1.0,
            "mean_delta": 0.01,
            "ci_low": 0.01,
            "ci_high": 0.01,
            "effect_size": 1.0,
        }
        payload.update(kwargs)
        verdict = evaluate_comparison(n_pairs=n_pairs, policy=ComparisonPolicy(), **payload)
        return verdict.outcome

    def test_a_single_cell_cannot_be_an_improvement(self) -> None:
        assert self._verdict(1) == "inconclusive"

    def test_below_the_minimum_is_always_inconclusive(self) -> None:
        for count in range(1, ComparisonPolicy().min_pairs):
            assert self._verdict(count) == "inconclusive", count

    def test_at_the_minimum_the_evidence_is_read_normally(self) -> None:
        assert self._verdict(ComparisonPolicy().min_pairs) == "improvement"

    def test_the_gate_is_named_in_the_verdict(self) -> None:
        verdict = evaluate_comparison(
            win_rate=1.0,
            mean_delta=0.01,
            ci_low=0.01,
            ci_high=0.01,
            effect_size=1.0,
            n_pairs=1,
            policy=ComparisonPolicy(),
        )
        assert any(gate.name == "enough_pairs" and not gate.passed for gate in verdict.gates)
        assert "paired cell" in verdict.rationale
