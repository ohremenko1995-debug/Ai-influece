"""Picking the takes a human should actually look at.

Ranking by score alone returns the same picture five times: the highest-scoring
frames of a batch are usually near-duplicates of each other. Maximal Marginal
Relevance (Carbonell & Goldstein, 1998) trades score against novelty, so the
shortlist covers the batch instead of clustering in one corner of it.

    MMR(i) = lambda * relevance(i) - (1 - lambda) * max_{j in chosen} similarity(i, j)

Similarity is taken in the *content* space, never the identity space. Penalising
identity similarity would reward the shortlist for drifting off-model, which is
the exact failure this whole tool exists to catch.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from identitylock.embeddings.base import Vector
from identitylock.metrics.diversity import distance_matrix


@dataclass(frozen=True, slots=True)
class SelectionResult:
    """Chosen indices, in pick order, with the diversity that was achieved."""

    indices: tuple[int, ...]
    mean_distance: float
    lambda_used: float

    def __len__(self) -> int:
        return len(self.indices)


def select_takes(
    relevance: Sequence[float],
    content: Sequence[Vector],
    *,
    k: int,
    lambda_: float = 0.7,
    eligible: Sequence[bool] | None = None,
) -> SelectionResult:
    """Greedy MMR over the eligible candidates.

    ``eligible`` is how the acceptance gate enters selection: a rejected take is
    never shortlisted, however good its score. Relevance is min-max normalised
    within the eligible set so the trade-off parameter means the same thing
    regardless of the score's scale.
    """
    if len(relevance) != len(content):
        raise ValueError("relevance and content must be the same length")
    if not 0.0 <= lambda_ <= 1.0:
        raise ValueError("lambda_ must lie in [0, 1]")

    pool = [
        index
        for index in range(len(relevance))
        if eligible is None or (index < len(eligible) and eligible[index])
    ]
    if not pool or k <= 0:
        return SelectionResult(indices=(), mean_distance=0.0, lambda_used=lambda_)

    scores = np.asarray([relevance[index] for index in pool], dtype=np.float64)
    span = float(scores.max() - scores.min())
    normalised = (scores - scores.min()) / span if span > 1e-12 else np.ones_like(scores)

    distances = distance_matrix([content[index] for index in pool])
    similarity = 1.0 - distances

    chosen: list[int] = []
    remaining = list(range(len(pool)))
    while remaining and len(chosen) < min(k, len(pool)):
        if not chosen:
            best = max(remaining, key=lambda local: normalised[local])
        else:
            best = max(
                remaining,
                key=lambda local: (
                    lambda_ * normalised[local]
                    - (1.0 - lambda_) * float(np.max(similarity[local, chosen]))
                ),
            )
        chosen.append(best)
        remaining.remove(best)

    if len(chosen) >= 2:
        picked = np.ix_(chosen, chosen)
        upper = distances[picked][np.triu_indices(len(chosen), k=1)]
        mean_distance = float(np.mean(upper))
    else:
        mean_distance = 0.0

    return SelectionResult(
        indices=tuple(pool[local] for local in chosen),
        mean_distance=mean_distance,
        lambda_used=lambda_,
    )
