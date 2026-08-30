"""Acceptance policy: the thresholds that turn measurements into decisions.

Two things this module deliberately does *not* do: it never looks at an image,
and it never computes a statistic. It takes numbers that are already measured and
applies a written rule to them. That separation is what lets the same policy be
re-applied to an archived run without regenerating anything.
"""

from __future__ import annotations

from pydantic import Field

from identitylock.domain.models import (
    CandidateMetrics,
    Comparison,
    ComparisonOutcome,
    ComparisonVerdict,
    Decision,
    GateOutcome,
    RunAggregates,
    RunVerdict,
    _Frozen,
    content_hash,
)


class Policy(_Frozen):
    """Per-candidate and per-run acceptance thresholds.

    Defaults are tuned for the bundled classical descriptor on the synthetic
    cohort. They are *not* universal constants — re-calibrate against your own
    reference set before trusting them (see ``docs/evaluation-protocol.md``).
    """

    identity_min: float = Field(default=0.70, ge=-1.0, le=1.0)
    """Cosine to the character centroid below which a take is off-model."""

    margin_min: float = Field(default=0.04, ge=0.0, le=2.0)
    """How far the take must sit from the closest impostor in the cohort."""

    technical_min: float = Field(default=0.40, ge=0.0, le=1.0)
    """Composite sharpness / exposure / contrast floor."""

    consistency_rate_min: float = Field(default=0.80, ge=0.0, le=1.0)
    """Share of the batch that must pass the per-candidate gates."""

    identity_p05_min: float = Field(default=0.60, ge=-1.0, le=1.0)
    """Fifth percentile floor — the worst takes, not the average one."""

    drift_abs_max: float = Field(default=0.050, ge=0.0, le=1.0)
    """Practical drift limit: max |slope| of identity per 10 frames.

    A product decision, not a fitted one — "the character may lose at most this
    much similarity over ten frames before the batch is not usable". Statistical
    significance alone must not fail a batch: with enough frames a slope of 0.001
    becomes significant and still means nothing."""

    drift_alpha: float = Field(default=0.05, gt=0.0, lt=0.5)
    """Significance level for the drift permutation test.

    The gate fails only when the slope is both *larger than* ``drift_abs_max`` and
    *steeper than chance* at this level. Requiring both is what stops the gate from
    firing on a batch whose four prompts simply differ in difficulty."""

    diversity_min: float = Field(default=0.08, ge=0.0, le=2.0)
    """Accepted takes must differ from each other; near-duplicates are not a batch."""

    def fingerprint(self) -> str:
        return content_hash(self.model_dump(mode="json"))


class ComparisonPolicy(_Frozen):
    """When an A/B is allowed to be called a win."""

    min_win_rate: float = Field(default=0.55, ge=0.0, le=1.0)
    min_effect_size: float = Field(default=0.15, ge=0.0)
    ci_level: float = Field(default=0.95, gt=0.5, lt=1.0)
    bootstrap_samples: int = Field(default=10_000, ge=200, le=200_000)

    def fingerprint(self) -> str:
        return content_hash(self.model_dump(mode="json"))


def evaluate_candidate(
    metrics: CandidateMetrics, policy: Policy
) -> tuple[Decision, tuple[str, ...]]:
    """Apply the per-candidate gates.

    A missing margin (a cohort of one) is not a failure and not a silent pass:
    the gate is skipped and the run report says the cohort was too small.
    """
    rejections: list[str] = []

    if metrics.identity_similarity < policy.identity_min:
        rejections.append(f"identity {metrics.identity_similarity:.3f} < {policy.identity_min:.3f}")
    if metrics.identity_margin is not None and metrics.identity_margin < policy.margin_min:
        rejections.append(f"margin {metrics.identity_margin:.3f} < {policy.margin_min:.3f}")
    if metrics.technical_score < policy.technical_min:
        rejections.append(f"technical {metrics.technical_score:.3f} < {policy.technical_min:.3f}")

    return ("reject" if rejections else "accept", tuple(rejections))


def evaluate_run(aggregates: RunAggregates, policy: Policy) -> RunVerdict:
    """Apply the run-level gates. This is what a CI job's exit code is built from."""
    gates = (
        GateOutcome(
            name="consistency_rate",
            passed=aggregates.consistency_rate >= policy.consistency_rate_min,
            observed=aggregates.consistency_rate,
            threshold=policy.consistency_rate_min,
            detail=f"{aggregates.n_accepted}/{aggregates.n_total} takes passed the candidate gates",
        ),
        GateOutcome(
            name="identity_p05",
            passed=aggregates.identity_p05 >= policy.identity_p05_min,
            observed=aggregates.identity_p05,
            threshold=policy.identity_p05_min,
            detail="fifth percentile of identity similarity across the batch",
        ),
        GateOutcome(
            name="drift",
            passed=(
                abs(aggregates.drift_slope) <= policy.drift_abs_max
                or aggregates.drift_p_value >= policy.drift_alpha
            ),
            observed=abs(aggregates.drift_slope),
            threshold=policy.drift_abs_max,
            detail=(
                f"identity slope per 10 frames; permutation p={aggregates.drift_p_value:.4f} "
                f"(alpha {policy.drift_alpha}), R^2={aggregates.drift_r2:.3f}"
            ),
        ),
        GateOutcome(
            name="diversity",
            passed=aggregates.diversity >= policy.diversity_min,
            observed=aggregates.diversity,
            threshold=policy.diversity_min,
            detail="mean pairwise content distance among accepted takes",
        ),
    )
    return RunVerdict(passed=all(gate.passed for gate in gates), gates=gates)


def evaluate_comparison(
    *,
    win_rate: float,
    mean_delta: float,
    ci_low: float,
    ci_high: float,
    effect_size: float,
    n_pairs: int,
    policy: ComparisonPolicy,
) -> ComparisonVerdict:
    """Decide an A/B.

    The confidence interval is the arbiter, not the mean. A challenger that wins
    on average but whose interval straddles zero is *inconclusive*, and saying so
    is the entire value of running the comparison.
    """
    gates = (
        GateOutcome(
            name="ci_excludes_zero",
            passed=ci_low > 0.0 or ci_high < 0.0,
            observed=ci_low if mean_delta >= 0 else ci_high,
            threshold=0.0,
            detail=f"{int(policy.ci_level * 100)}% bootstrap CI [{ci_low:+.4f}, {ci_high:+.4f}]",
        ),
        GateOutcome(
            name="win_rate",
            passed=win_rate >= policy.min_win_rate,
            observed=win_rate,
            threshold=policy.min_win_rate,
            detail=f"challenger won {win_rate:.0%} of {n_pairs} paired cells",
        ),
        GateOutcome(
            name="effect_size",
            passed=abs(effect_size) >= policy.min_effect_size,
            observed=abs(effect_size),
            threshold=policy.min_effect_size,
            detail="matched-pairs rank-biserial correlation on the paired differences",
        ),
    )

    outcome: ComparisonOutcome
    if ci_high < 0.0:
        outcome = "regression"
        rationale = (
            f"The whole confidence interval sits below zero "
            f"([{ci_low:+.4f}, {ci_high:+.4f}]); the challenger is worse."
        )
    elif all(gate.passed for gate in gates) and mean_delta > 0.0:
        outcome = "improvement"
        rationale = (
            f"Challenger wins {win_rate:.0%} of {n_pairs} paired cells, "
            f"mean {mean_delta:+.4f}, CI [{ci_low:+.4f}, {ci_high:+.4f}]."
        )
    else:
        outcome = "inconclusive"
        failed = ", ".join(gate.name for gate in gates if not gate.passed) or "no gate"
        rationale = (
            f"Not enough evidence to call it: {failed} did not clear. "
            f"Mean {mean_delta:+.4f}, CI [{ci_low:+.4f}, {ci_high:+.4f}]."
        )

    return ComparisonVerdict(outcome=outcome, gates=gates, rationale=rationale)


def comparison_exit_code(comparison: Comparison) -> int:
    """0 for improvement or inconclusive, 1 for a measured regression."""
    return 1 if comparison.verdict.outcome == "regression" else 0
