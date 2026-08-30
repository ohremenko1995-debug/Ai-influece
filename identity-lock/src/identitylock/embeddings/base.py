"""The embedding contract.

One protocol, two vectors. Every backend — the bundled classical descriptor, a
CLIP tower, a face-recognition model — returns the same pair, so the metric layer
never learns which one it is talking to.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

import numpy as np
from numpy.typing import NDArray

from identitylock.imaging.loader import Image

Vector = NDArray[np.float32]


@dataclass(frozen=True, slots=True)
class Descriptor:
    """Two L2-normalised views of one frame.

    Keeping them apart is the central design decision of this tool. Identity
    consistency and scene variety pull in opposite directions: a batch where every
    frame is identical scores perfectly on identity and is worthless. Measuring
    "is this the same character" on one vector and "is this a different picture"
    on another lets a policy demand both at once.
    """

    identity: Vector
    """Subject-centred structure, texture and palette. High cosine = same character."""

    content: Vector
    """Global composition, lighting and colour layout. High cosine = same picture."""

    def __post_init__(self) -> None:
        if self.identity.ndim != 1 or self.content.ndim != 1:
            raise ValueError("descriptor vectors must be one-dimensional")


@runtime_checkable
class Embedder(Protocol):
    """What the metric layer requires of any backend."""

    @property
    def name(self) -> str:
        """Stable identifier recorded in the run manifest."""

    @property
    def identity_dim(self) -> int:
        """Length of the identity vector, also recorded in the manifest."""

    def describe(self, image: Image) -> Descriptor:
        """Describe one normalised frame."""


def l2_normalise(vector: Vector) -> Vector:
    """Unit-length, with an explicit zero-vector answer instead of a NaN."""
    norm = float(np.linalg.norm(vector))
    if norm <= 1e-12:
        return np.zeros_like(vector)
    return np.asarray(vector / norm, dtype=np.float32)


def cosine(left: Vector, right: Vector) -> float:
    """Cosine similarity. Inputs are expected normalised; this does not assume it."""
    denominator = float(np.linalg.norm(left)) * float(np.linalg.norm(right))
    if denominator <= 1e-12:
        return 0.0
    return float(np.clip(float(np.dot(left, right)) / denominator, -1.0, 1.0))
