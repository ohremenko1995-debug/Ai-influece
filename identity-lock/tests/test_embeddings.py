"""Descriptor behaviour: determinism, shape, and the invariances it claims."""

from __future__ import annotations

import numpy as np
import pytest

from identitylock.embeddings import (
    ClassicalEmbedder,
    cosine,
    get_embedder,
    l2_normalise,
    registered,
)
from identitylock.embeddings.classical import rgb_to_hsv
from identitylock.embeddings.learned import MissingBackendError
from identitylock.providers.synthetic import render, scene_for, traits_for


def _frame(character: str, seed: int, size: int = 128) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return render(traits_for(character), scene_for("p", seed), size, grain=0.01, rng=rng)


class TestNormalisation:
    def test_unit_length(self) -> None:
        vector = l2_normalise(np.array([3.0, 4.0], dtype=np.float32))
        assert float(np.linalg.norm(vector)) == pytest.approx(1.0)

    def test_zero_vector_stays_zero_instead_of_nan(self) -> None:
        vector = l2_normalise(np.zeros(4, dtype=np.float32))
        assert not np.any(np.isnan(vector))

    def test_cosine_of_zero_vectors_is_zero(self) -> None:
        assert cosine(np.zeros(3, dtype=np.float32), np.ones(3, dtype=np.float32)) == 0.0

    def test_cosine_is_bounded(self) -> None:
        rng = np.random.default_rng(0)
        for _ in range(20):
            left = rng.normal(size=8).astype(np.float32)
            right = rng.normal(size=8).astype(np.float32)
            assert -1.0 <= cosine(left, right) <= 1.0


class TestHsv:
    def test_matches_known_colours(self) -> None:
        image = np.array([[[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]], dtype=np.float32)
        hsv = rgb_to_hsv(image)
        assert hsv[0, 0, 0] == pytest.approx(0.0, abs=1e-5)
        assert hsv[0, 1, 0] == pytest.approx(1 / 3, abs=1e-5)
        assert hsv[0, 2, 0] == pytest.approx(2 / 3, abs=1e-5)
        assert np.allclose(hsv[..., 1], 1.0)

    def test_greys_have_zero_saturation(self) -> None:
        grey = np.full((4, 4, 3), 0.42, dtype=np.float32)
        assert float(np.max(rgb_to_hsv(grey)[..., 1])) == pytest.approx(0.0, abs=1e-6)


class TestClassicalEmbedder:
    def test_reports_its_dimension(self) -> None:
        embedder = ClassicalEmbedder()
        assert embedder.identity_dim == len(embedder.describe(_frame("a", 1)).identity)

    def test_is_deterministic(self) -> None:
        embedder = ClassicalEmbedder()
        frame = _frame("a", 1)
        assert np.array_equal(embedder.describe(frame).identity, embedder.describe(frame).identity)

    def test_vectors_are_unit_length(self) -> None:
        descriptor = ClassicalEmbedder().describe(_frame("a", 1))
        assert float(np.linalg.norm(descriptor.identity)) == pytest.approx(1.0, abs=1e-5)
        assert float(np.linalg.norm(descriptor.content)) == pytest.approx(1.0, abs=1e-5)

    def test_is_resolution_independent(self) -> None:
        """The same subject at two resolutions must not read as two characters."""
        embedder = ClassicalEmbedder()
        small = embedder.describe(_frame("a", 1, size=128)).identity
        large = embedder.describe(_frame("a", 1, size=384)).identity
        assert cosine(small, large) > 0.95

    def test_separates_two_characters(self) -> None:
        embedder = ClassicalEmbedder()
        same = cosine(
            embedder.describe(_frame("a", 1)).identity, embedder.describe(_frame("a", 2)).identity
        )
        different = cosine(
            embedder.describe(_frame("a", 1)).identity, embedder.describe(_frame("b", 1)).identity
        )
        assert same > different

    def test_rejects_a_nonsense_crop(self) -> None:
        with pytest.raises(ValueError, match="identity_crop"):
            ClassicalEmbedder(identity_crop=0.0)

    def test_rejects_bad_block_weights(self) -> None:
        with pytest.raises(ValueError, match="block_weights"):
            ClassicalEmbedder(block_weights=(1.0, -1.0, 0.0))

    def test_survives_a_degenerate_image(self) -> None:
        flat = np.full((16, 16, 3), 0.5, dtype=np.float32)
        descriptor = ClassicalEmbedder().describe(flat)
        assert not np.any(np.isnan(descriptor.identity))


class TestRegistry:
    def test_lists_every_backend(self) -> None:
        assert {"classical", "clip", "arcface"} <= set(registered())

    def test_default_is_the_classical_descriptor(self) -> None:
        assert get_embedder().name == "classical-v1"

    def test_unknown_backend_lists_the_known_ones(self) -> None:
        with pytest.raises(ValueError, match="Available: arcface, classical, clip"):
            get_embedder("nope")

    def test_a_missing_dependency_says_how_to_install_it(self) -> None:
        """A learned backend is never silently swapped for the classical one."""
        with pytest.raises(MissingBackendError, match="pip install"):
            get_embedder("clip")
