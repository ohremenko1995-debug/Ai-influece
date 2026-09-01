"""The identity space a similarity is measured in.

A raw histogram descriptor has a large component every natural image shares —
mid-grey luminance, a broad edge distribution, a skin-ish hue mass. Cosine
against the raw vectors therefore sits near 0.95 for *any* two portraits, and the
signal that matters is buried in the third decimal.

Centring on the cohort mean removes that shared component. The remaining vector
is what makes this character different from the others being tracked, and cosine
in the centred space spreads across a usable range. This is the standard
"centre then renormalise" step from face-verification pipelines, done explicitly
and recorded in the run manifest rather than hidden inside a backend.

A learned backend whose cosine is already calibrated (ArcFace) can skip it with
``IdentitySpace.unit(dim)``.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from identitylock.domain.models import content_hash
from identitylock.embeddings.base import Vector, l2_normalise


@dataclass(frozen=True, slots=True)
class IdentitySpace:
    """A fitted centring transform, plus the fingerprint that identifies it."""

    mean: Vector
    n_fitted: int
    centred: bool

    @classmethod
    def fit(cls, vectors: Sequence[Vector]) -> IdentitySpace:
        """Fit on every reference vector in the cohort — all characters, pooled.

        Pooling across characters is deliberate. Centring on a single character's
        own references would subtract exactly what distinguishes them and drive
        every similarity toward zero.
        """
        if not vectors:
            raise ValueError("cannot fit an identity space on zero vectors")
        stacked = np.stack([np.asarray(vector, dtype=np.float32) for vector in vectors])
        return cls(
            mean=np.asarray(stacked.mean(axis=0), dtype=np.float32),
            n_fitted=len(vectors),
            centred=True,
        )

    @classmethod
    def unit(cls, dim: int) -> IdentitySpace:
        """The no-op space, for backends whose cosine is already meaningful."""
        return cls(mean=np.zeros(dim, dtype=np.float32), n_fitted=0, centred=False)

    def project(self, vector: Vector) -> Vector:
        if not self.centred:
            return l2_normalise(np.asarray(vector, dtype=np.float32))
        return l2_normalise(np.asarray(vector, dtype=np.float32) - self.mean)

    def project_all(self, vectors: Sequence[Vector]) -> tuple[Vector, ...]:
        return tuple(self.project(vector) for vector in vectors)

    def fingerprint(self) -> str:
        """Content address of the transform, so two runs can prove they share one."""
        return content_hash(
            {
                "centred": self.centred,
                "n_fitted": self.n_fitted,
                "mean": [round(float(value), 8) for value in self.mean],
            }
        )
