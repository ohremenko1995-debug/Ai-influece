"""Content diversity: the counterweight to identity consistency.

Identity consistency alone is trivially maximised by generating the same frame
every time. Diversity is measured in the *content* space, so a batch can be
required to hold the character steady while the pictures actually differ.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
from numpy.typing import NDArray

from identitylock.embeddings.base import Vector


def distance_matrix(vectors: Sequence[Vector]) -> NDArray[np.float64]:
    """Pairwise cosine distance (``1 - cosine``) as a dense square matrix."""
    if not vectors:
        return np.zeros((0, 0), dtype=np.float64)
    stacked = np.stack([np.asarray(vector, dtype=np.float64) for vector in vectors])
    norms = np.linalg.norm(stacked, axis=1, keepdims=True)
    norms[norms <= 1e-12] = 1.0
    unit = stacked / norms
    return np.asarray(np.clip(1.0 - unit @ unit.T, 0.0, 2.0), dtype=np.float64)


def mean_pairwise_distance(vectors: Sequence[Vector]) -> float:
    """Mean content distance over every unordered pair. 0.0 for fewer than two."""
    count = len(vectors)
    if count < 2:
        return 0.0
    matrix = distance_matrix(vectors)
    return float(np.mean(matrix[np.triu_indices(count, k=1)]))


def duplicate_pairs(
    vectors: Sequence[Vector], *, threshold: float = 0.02
) -> tuple[tuple[int, int], ...]:
    """Index pairs closer than ``threshold`` — near-duplicate takes.

    Useful on its own: a batch that passes the diversity gate on average can still
    contain two frames that are the same picture, and a human picking takes wants
    to know which two.
    """
    count = len(vectors)
    if count < 2:
        return ()
    matrix = distance_matrix(vectors)
    rows, cols = np.triu_indices(count, k=1)
    close = matrix[rows, cols] <= threshold
    return tuple((int(rows[index]), int(cols[index])) for index in np.flatnonzero(close))
