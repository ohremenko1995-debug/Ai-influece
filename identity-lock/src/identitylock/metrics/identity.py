"""Identity measurement: how close a take is to the character, and to everyone else."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from identitylock.embeddings.base import Vector, cosine, l2_normalise
from identitylock.metrics.aggregate import linear_trend


@dataclass(frozen=True, slots=True)
class ReferenceProfile:
    """A character's reference set reduced to what the metrics need.

    ``coherence`` is the mean pairwise cosine *within* the reference set. It is a
    property of the references, not of any generated take, and it is the first
    number to look at when results look wrong: a centroid built from references
    that disagree with each other is not a target, it is an average of two
    different people.
    """

    character_id: str
    centroid: Vector
    vectors: tuple[Vector, ...]
    coherence: float
    hashes: tuple[str, ...]

    @property
    def size(self) -> int:
        return len(self.vectors)


def build_profile(
    character_id: str,
    vectors: Sequence[Vector],
    hashes: Sequence[str] = (),
) -> ReferenceProfile:
    """Reduce a set of projected reference vectors to a profile."""
    if not vectors:
        raise ValueError(f"character '{character_id}' has no reference images")
    stacked = np.stack([np.asarray(vector, dtype=np.float32) for vector in vectors])
    centroid = l2_normalise(np.asarray(stacked.mean(axis=0), dtype=np.float32))
    return ReferenceProfile(
        character_id=character_id,
        centroid=centroid,
        vectors=tuple(np.asarray(vector, dtype=np.float32) for vector in vectors),
        coherence=mean_pairwise_cosine(vectors),
        hashes=tuple(hashes),
    )


def mean_pairwise_cosine(vectors: Sequence[Vector]) -> float:
    """Mean cosine over every unordered pair. 1.0 for a single vector."""
    count = len(vectors)
    if count < 2:
        return 1.0
    stacked = np.stack([np.asarray(vector, dtype=np.float32) for vector in vectors])
    gram = stacked @ stacked.T
    upper = gram[np.triu_indices(count, k=1)]
    return float(np.mean(upper))


def similarity(vector: Vector, profile: ReferenceProfile) -> float:
    """Cosine against the character centroid. The headline identity number."""
    return cosine(vector, profile.centroid)


def nearest_reference(vector: Vector, profile: ReferenceProfile) -> float:
    """Best cosine against any single reference.

    Complements the centroid: a take can sit far from the average of the
    references while matching one of them closely, which usually means the
    reference set spans two looks rather than one.
    """
    return max(cosine(vector, reference) for reference in profile.vectors)


def impostor_margin(
    vector: Vector,
    own: ReferenceProfile,
    impostors: Sequence[ReferenceProfile],
) -> tuple[float | None, float | None, str | None]:
    """Similarity to the character minus similarity to the closest other character.

    Returns ``(margin, best_impostor_similarity, impostor_id)``, or three ``None``
    values when the cohort holds nobody else. A high similarity means little on
    its own — if every character in the cohort scores 0.9 against this frame, the
    descriptor is measuring "a portrait", not "this portrait". The margin is what
    makes the claim falsifiable.
    """
    others = [profile for profile in impostors if profile.character_id != own.character_id]
    if not others:
        return (None, None, None)
    scores = [(cosine(vector, profile.centroid), profile.character_id) for profile in others]
    best_score, best_id = max(scores, key=lambda item: item[0])
    return (similarity(vector, own) - best_score, best_score, best_id)


def drift(series: Sequence[float], *, per: int = 10) -> tuple[float, float]:
    """Identity slope across the batch, per ``per`` frames, with its R^2."""
    return linear_trend(series, per=per)
