"""Statistics, kept in one place and kept honest.

Three rules this module follows:

1. **Report intervals, not just point estimates.** A mean identity of 0.81 with a
   95% interval of [0.62, 0.93] is a different fact from 0.81 +/- 0.01, and a
   report that prints only the first number is hiding the second.
2. **Be non-parametric.** Identity similarity is bounded, skewed and small-n.
   A bootstrap makes no distributional promise it cannot keep.
3. **Be reproducible.** Every resampling function takes an explicit seed and is
   deterministic given it, so the same run always produces the same interval.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
from numpy.typing import NDArray

Floats = Sequence[float] | NDArray[np.float64]


def _as_array(values: Floats) -> NDArray[np.float64]:
    return np.asarray(list(values) if isinstance(values, Sequence) else values, dtype=np.float64)


def mean(values: Floats) -> float:
    array = _as_array(values)
    return float(np.mean(array)) if array.size else 0.0


def std(values: Floats, *, ddof: int = 1) -> float:
    """Sample standard deviation. Zero for fewer than two observations."""
    array = _as_array(values)
    if array.size <= ddof:
        return 0.0
    return float(np.std(array, ddof=ddof))


def percentile(values: Floats, q: float) -> float:
    """Linear-interpolated percentile, ``q`` in [0, 100]."""
    array = _as_array(values)
    if array.size == 0:
        return 0.0
    return float(np.percentile(array, q))


def bootstrap_ci(
    values: Floats,
    *,
    level: float = 0.95,
    samples: int = 10_000,
    seed: int = 20240101,
) -> tuple[float, float]:
    """Percentile bootstrap interval for the mean.

    The percentile method, not BCa: it is transparent, it needs no jackknife pass
    and for the near-symmetric paired differences this harness bootstraps the two
    agree closely. For a heavily skewed statistic prefer BCa and say so — the
    limitation is recorded in ``docs/metrics.md`` rather than papered over.
    """
    array = _as_array(values)
    if array.size == 0:
        return (0.0, 0.0)
    if array.size == 1:
        single = float(array[0])
        return (single, single)

    rng = np.random.default_rng(seed)
    indices = rng.integers(0, array.size, size=(samples, array.size))
    means = array[indices].mean(axis=1)
    tail = (1.0 - level) / 2.0
    low, high = np.percentile(means, [tail * 100.0, (1.0 - tail) * 100.0])
    return (float(low), float(high))


def win_rate(deltas: Floats, *, tolerance: float = 0.0) -> float:
    """Share of paired cells the challenger wins.

    Ties (|delta| <= tolerance) count as half a win to each side, which is the
    standard treatment and keeps a run of identical outputs at exactly 0.5
    instead of collapsing it to 0.0.
    """
    array = _as_array(deltas)
    if array.size == 0:
        return 0.0
    wins = float(np.sum(array > tolerance))
    ties = float(np.sum(np.abs(array) <= tolerance))
    return float((wins + 0.5 * ties) / array.size)


def rank_biserial(deltas: Floats) -> float:
    """Matched-pairs rank-biserial correlation, in [-1, 1].

    The paired-design effect size: the normalised difference between the summed
    ranks of positive and negative differences. Zero differences are dropped, as
    in the Wilcoxon signed-rank test it derives from. Unlike Cohen's d it makes
    no normality assumption, and unlike a raw mean it is not moved by one outlier.
    """
    array = _as_array(deltas)
    nonzero = array[array != 0.0]
    if nonzero.size == 0:
        return 0.0

    order = np.argsort(np.abs(nonzero), kind="stable")
    ranks = np.empty(nonzero.size, dtype=np.float64)
    ranks[order] = np.arange(1, nonzero.size + 1, dtype=np.float64)

    positive = float(np.sum(ranks[nonzero > 0.0]))
    negative = float(np.sum(ranks[nonzero < 0.0]))
    total = positive + negative
    return float((positive - negative) / total) if total > 0.0 else 0.0


def cliffs_delta(baseline: Floats, challenger: Floats) -> float:
    """Two-sample dominance statistic, in [-1, 1].

    Provided for unpaired comparisons. The paired A/B path uses
    :func:`rank_biserial` instead, because throwing away the pairing would inflate
    the variance for no reason.
    """
    left = _as_array(baseline)
    right = _as_array(challenger)
    if left.size == 0 or right.size == 0:
        return 0.0
    greater = float(np.sum(right[:, None] > left[None, :]))
    lesser = float(np.sum(right[:, None] < left[None, :]))
    return float((greater - lesser) / (left.size * right.size))


def linear_trend(values: Floats, *, per: int = 10) -> tuple[float, float]:
    """Ordinary least squares of the series against its index.

    Returns ``(slope_per_<per>_steps, r_squared)``. This is the drift measurement:
    a batch whose identity slides downward as the frames go by is a different
    failure from a batch that is uniformly mediocre, and only the slope separates
    them. R^2 travels with the slope so a large slope fitted to noise can be
    recognised as exactly that.
    """
    array = _as_array(values)
    if array.size < 2:
        return (0.0, 0.0)

    index = np.arange(array.size, dtype=np.float64)
    index_centred = index - index.mean()
    values_centred = array - array.mean()
    denominator = float(np.sum(index_centred**2))
    if denominator <= 0.0:
        return (0.0, 0.0)

    slope = float(np.sum(index_centred * values_centred) / denominator)
    predicted = array.mean() + slope * index_centred
    residual = float(np.sum((array - predicted) ** 2))
    total = float(np.sum(values_centred**2))
    r_squared = 0.0 if total <= 0.0 else float(1.0 - residual / total)
    return (slope * per, max(0.0, r_squared))


def stratified_drift(
    values: Floats,
    groups: Sequence[str] | None = None,
    *,
    per: int = 10,
    permutations: int = 5_000,
    seed: int = 20240101,
) -> tuple[float, float, float]:
    """Drift slope, R^2 and permutation p-value, with group effects removed.

    Returns ``(slope_per_<per>_steps, r_squared, p_value)``.

    Two corrections, both about not measuring the wrong thing:

    **Group centring.** ``groups`` labels each observation — in practice, which
    prompt produced it. Subtracting each group's mean before fitting removes
    "the night shot is simply harder" from the slope, leaving only the part of the
    variation that tracks position in the batch.

    **Stratified permutation.** The null reshuffles values *within* each group,
    never across. Shuffling across groups would build a null in which the prompt
    mix itself varies, making the observed slope look extreme for a reason that has
    nothing to do with drift. Within-group shuffling holds the prompt structure
    fixed and destroys only the ordering, which is exactly the hypothesis under test.

    With no groups this degenerates to an ordinary permutation test on the series.
    """
    array = _as_array(values)
    if array.size < 3:
        return (0.0, 0.0, 1.0)

    labels = list(groups) if groups is not None else ["_"] * array.size
    if len(labels) != array.size:
        raise ValueError("groups must be the same length as values")

    strata: dict[str, list[int]] = {}
    for position, label in enumerate(labels):
        strata.setdefault(label, []).append(position)

    residuals = array.copy()
    for positions in strata.values():
        residuals[positions] -= float(np.mean(array[positions]))

    index = np.arange(array.size, dtype=np.float64)
    centred_index = index - index.mean()
    denominator = float(np.sum(centred_index**2))
    if denominator <= 0.0:
        return (0.0, 0.0, 1.0)

    observed_raw = float(np.sum(centred_index * (residuals - residuals.mean())) / denominator)
    observed = observed_raw * per

    predicted = residuals.mean() + observed_raw * centred_index
    total = float(np.sum((residuals - residuals.mean()) ** 2))
    r_squared = (
        0.0 if total <= 0.0 else max(0.0, 1.0 - float(np.sum((residuals - predicted) ** 2)) / total)
    )

    rng = np.random.default_rng(seed)
    shuffled = np.empty((permutations, array.size), dtype=np.float64)
    for positions in strata.values():
        block = np.tile(residuals[positions], (permutations, 1))
        shuffled[:, positions] = rng.permuted(block, axis=1)

    centred = shuffled - shuffled.mean(axis=1, keepdims=True)
    slopes = (centred @ centred_index) / denominator * per
    hits = int(np.sum(np.abs(slopes) >= abs(observed)))

    return (observed, r_squared, float((1 + hits) / (1 + permutations)))
