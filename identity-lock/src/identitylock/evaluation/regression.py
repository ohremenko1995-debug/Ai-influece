"""A/B between two runs of the same suite.

The design is paired: every cell is the same prompt and the same seed under two
recipes, so the difference between them cannot be explained by "it drew a
different picture". Pairing is not a nicety — an unpaired comparison of twenty
frames per side is dominated by scene variance and would need an order of
magnitude more samples to see the same effect.

The harness refuses to compare two runs whose plans differ. A comparison that
silently intersects two different suites is worse than no comparison, because it
still prints a confident number.
"""

from __future__ import annotations

from collections.abc import Callable

from identitylock.domain.models import (
    Comparison,
    PairedDelta,
    RunResult,
    ScoredCandidate,
    content_hash,
)
from identitylock.domain.policy import ComparisonPolicy, evaluate_comparison
from identitylock.metrics.aggregate import bootstrap_ci, mean, rank_biserial, win_rate

METRICS: dict[str, Callable[[ScoredCandidate], float]] = {
    "identity": lambda item: item.metrics.identity_similarity,
    "margin": lambda item: item.metrics.identity_margin or 0.0,
    "technical": lambda item: item.metrics.technical_score,
    "nearest_reference": lambda item: item.metrics.nearest_reference,
}


class ComparisonError(ValueError):
    """The two runs cannot be honestly compared."""


def _check_comparable(baseline: RunResult, challenger: RunResult) -> None:
    if baseline.suite.id != challenger.suite.id:
        raise ComparisonError(
            f"Different suites: '{baseline.suite.id}' vs '{challenger.suite.id}'."
        )
    if baseline.suite.character.id != challenger.suite.character.id:
        raise ComparisonError(
            f"Different characters: '{baseline.suite.character.id}' vs "
            f"'{challenger.suite.character.id}'."
        )
    if set(baseline.by_cell()) != set(challenger.by_cell()):
        raise ComparisonError(
            "The two runs do not cover the same (prompt, seed) cells, so the "
            "comparison would not be paired. Re-run both sides from the same suite."
        )
    if baseline.manifest.embedder != challenger.manifest.embedder:
        raise ComparisonError(
            f"Different embedders ('{baseline.manifest.embedder}' vs "
            f"'{challenger.manifest.embedder}'); the similarities are not on the same scale."
        )
    if baseline.manifest.reference_hashes != challenger.manifest.reference_hashes:
        raise ComparisonError(
            "The two runs were scored against different reference images. "
            "Identity numbers from different yardsticks are not comparable."
        )
    if baseline.manifest.identity_space != challenger.manifest.identity_space:
        raise ComparisonError(
            "The two runs were measured in different identity spaces "
            f"({baseline.manifest.identity_space} vs {challenger.manifest.identity_space}). "
            "The cohort or its references changed between them, so every cosine was "
            "taken against a different centring and the differences are not paired."
        )
    if baseline.manifest.recipe_revision == challenger.manifest.recipe_revision:
        raise ComparisonError(
            "Both runs used the same recipe revision "
            f"({baseline.manifest.recipe_revision}); there is nothing to compare."
        )


def compare(
    baseline: RunResult,
    challenger: RunResult,
    *,
    metric: str = "identity",
    policy: ComparisonPolicy | None = None,
    seed: int = 20240101,
) -> Comparison:
    """Score the challenger against the baseline on one metric."""
    if metric not in METRICS:
        raise ComparisonError(f"Unknown metric '{metric}'. Available: {', '.join(sorted(METRICS))}")
    _check_comparable(baseline, challenger)

    policy = policy or ComparisonPolicy()
    extract = METRICS[metric]
    left = baseline.by_cell()
    right = challenger.by_cell()

    pairs = tuple(
        PairedDelta(
            prompt_id=prompt_id,
            seed=seed_value,
            baseline=round(extract(left[(prompt_id, seed_value)]), 6),
            challenger=round(extract(right[(prompt_id, seed_value)]), 6),
        )
        for prompt_id, seed_value in sorted(left)
    )
    deltas = [pair.delta for pair in pairs]

    mean_delta = mean(deltas)
    low, high = bootstrap_ci(
        deltas, level=policy.ci_level, samples=policy.bootstrap_samples, seed=seed
    )
    rate = win_rate(deltas)
    effect = rank_biserial(deltas)

    verdict = evaluate_comparison(
        win_rate=rate,
        mean_delta=mean_delta,
        ci_low=low,
        ci_high=high,
        effect_size=effect,
        n_pairs=len(pairs),
        policy=policy,
    )

    return Comparison(
        comparison_id=f"cmp.{baseline.suite.id}.{metric}."
        + content_hash([baseline.run_id, challenger.run_id, metric]),
        metric=metric,
        baseline_run_id=baseline.run_id,
        baseline_label=baseline.label,
        challenger_run_id=challenger.run_id,
        challenger_label=challenger.label,
        pairs=pairs,
        win_rate=round(rate, 6),
        mean_delta=round(mean_delta, 6),
        ci_low=round(low, 6),
        ci_high=round(high, 6),
        effect_size=round(effect, 6),
        n_pairs=len(pairs),
        verdict=verdict,
    )
