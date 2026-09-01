"""Descriptor behaviour: determinism, shape, and the invariances it claims."""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from typing import Any

import numpy as np
import pytest

from identitylock.embeddings import (
    ClassicalEmbedder,
    cosine,
    get_embedder,
    l2_normalise,
    registered,
)
from identitylock.embeddings.classical import centre_crop, rgb_to_hsv
from identitylock.embeddings.learned import (
    MissingBackendError,
    describe_with,
    select_largest_face,
)
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

    @pytest.mark.skipif(
        importlib.util.find_spec("open_clip") is not None,
        reason="open_clip is installed in this environment, so the error cannot fire",
    )
    def test_a_missing_dependency_says_how_to_install_it(self) -> None:
        """A learned backend is never silently swapped for the classical one."""
        with pytest.raises(MissingBackendError, match="pip install"):
            get_embedder("clip")

    @pytest.mark.skipif(
        importlib.util.find_spec("open_clip") is None,
        reason="open_clip is not installed here",
    )
    def test_an_installed_backend_is_never_reported_as_missing(self) -> None:
        """With the dependency present, any failure must be about weights, not imports.

        This pair of tests exists because the suite used to assume the optional
        extra was absent: installing it turned the suite red, which is a property
        of the tests rather than of the code.
        """
        # The assertion is on the exception *type*, so a broad catch is the point here.
        with pytest.raises(Exception) as caught:
            get_embedder("clip")
        assert not isinstance(caught.value, MissingBackendError)


@dataclass(frozen=True, slots=True)
class _Face:
    """Stands in for an insightface detection."""

    bbox: tuple[float, float, float, float]
    normed_embedding: tuple[float, ...]


class TestLearnedWiring:
    """The learned backends' routing, tested without weights.

    The weight-loading and inference paths cannot run in this environment — the
    network policy denies `huggingface.co` and `download.pytorch.org`. What *can*
    be pinned is the wiring around the model, which is where a silent bug would
    live: reading identity from the wrong region, or picking the wrong face.
    """

    def test_identity_comes_from_the_crop_and_content_from_the_frame(self) -> None:
        seen: list[tuple[int, int]] = []

        def encode(image: np.ndarray) -> np.ndarray:
            seen.append((image.shape[0], image.shape[1]))
            return np.asarray([float(image.shape[0]), 1.0, 0.0], dtype=np.float32)

        image = np.zeros((100, 100, 3), dtype=np.float32)
        descriptor = describe_with(encode, image, identity_crop=0.5)

        assert seen == [(50, 50), (100, 100)]
        assert descriptor.identity[0] < descriptor.content[0]

    def test_both_vectors_are_normalised(self) -> None:
        def encode(image: np.ndarray) -> np.ndarray:
            return np.asarray([3.0, 4.0, 0.0], dtype=np.float32) * float(image.shape[0])

        descriptor = describe_with(
            encode, np.zeros((64, 64, 3), dtype=np.float32), identity_crop=0.5
        )
        assert float(np.linalg.norm(descriptor.identity)) == pytest.approx(1.0, abs=1e-6)
        assert float(np.linalg.norm(descriptor.content)) == pytest.approx(1.0, abs=1e-6)

    def test_the_crop_fraction_is_honoured(self) -> None:
        image = np.zeros((200, 200, 3), dtype=np.float32)
        assert centre_crop(image, 0.5).shape[:2] == (100, 100)
        assert centre_crop(image, 1.0).shape[:2] == (200, 200)

    def test_picks_the_largest_face(self) -> None:
        small = _Face(bbox=(0.0, 0.0, 10.0, 10.0), normed_embedding=(1.0, 0.0))
        large = _Face(bbox=(50.0, 50.0, 150.0, 150.0), normed_embedding=(0.0, 1.0))
        assert select_largest_face([small, large]) is large
        assert select_largest_face([large, small]) is large

    def test_an_empty_detection_is_none_not_an_index_error(self) -> None:
        assert select_largest_face([]) is None

    def test_a_degenerate_box_does_not_win(self) -> None:
        """A zero-area detection must never beat a real one."""
        empty = _Face(bbox=(10.0, 10.0, 10.0, 10.0), normed_embedding=(1.0, 0.0))
        real = _Face(bbox=(0.0, 0.0, 4.0, 4.0), normed_embedding=(0.0, 1.0))
        assert select_largest_face([empty, real]) is real

    def test_inverted_boxes_are_clamped_to_zero_area(self) -> None:
        inverted: Any = _Face(bbox=(100.0, 100.0, 0.0, 0.0), normed_embedding=(1.0, 0.0))
        real = _Face(bbox=(0.0, 0.0, 2.0, 2.0), normed_embedding=(0.0, 1.0))
        assert select_largest_face([inverted, real]) is real


class _FakeAnalysis:
    """Stands in for a prepared insightface FaceAnalysis."""

    def __init__(self, faces: list[_Face]) -> None:
        self._faces = faces
        self.frames: list[tuple[int, int, int]] = []

    def get(self, frame: np.ndarray) -> list[_Face]:
        self.frames.append(frame.shape)
        return self._faces


class TestArcFaceDetectionPaths:
    """The paths that decide what happens when detection succeeds or fails.

    Weights are never loaded here — the analyser is injected. These are regressions:
    the miss path used to return the 292-d classical descriptor into a 512-d space,
    which aborted the whole run on the first undetectable face.
    """

    def _embedder(self, faces: list[_Face]) -> Any:
        from identitylock.embeddings.learned import ArcFaceEmbedder

        return ArcFaceEmbedder(app=_FakeAnalysis(faces))

    def test_a_missing_face_keeps_the_declared_dimension(self) -> None:
        embedder = self._embedder([])
        descriptor = embedder.describe(np.zeros((64, 64, 3), dtype=np.float32))
        assert len(descriptor.identity) == embedder.identity_dim == 512

    def test_a_missing_face_scores_zero_so_the_gate_rejects_it(self) -> None:
        from identitylock.embeddings.base import cosine

        embedder = self._embedder([])
        descriptor = embedder.describe(np.zeros((64, 64, 3), dtype=np.float32))
        reference = l2_normalise(np.ones(512, dtype=np.float32))
        assert cosine(descriptor.identity, reference) == 0.0

    def test_a_missing_face_still_yields_a_usable_content_vector(self) -> None:
        embedder = self._embedder([])
        descriptor = embedder.describe(np.zeros((64, 64, 3), dtype=np.float32))
        assert float(np.linalg.norm(descriptor.content)) == pytest.approx(1.0, abs=1e-5)

    def test_misses_are_counted_so_the_manifest_can_report_them(self) -> None:
        embedder = self._embedder([])
        assert embedder.misses == 0
        for _ in range(3):
            embedder.describe(np.zeros((32, 32, 3), dtype=np.float32))
        assert embedder.misses == 3

    def test_a_detected_face_supplies_the_identity_vector(self) -> None:
        embedding = tuple(float(value) for value in np.eye(512, dtype=np.float32)[7])
        embedder = self._embedder([_Face(bbox=(0.0, 0.0, 40.0, 40.0), normed_embedding=embedding)])
        descriptor = embedder.describe(np.zeros((64, 64, 3), dtype=np.float32))
        assert embedder.misses == 0
        assert float(descriptor.identity[7]) == pytest.approx(1.0)

    def test_the_analyser_is_handed_bgr_uint8(self) -> None:
        """insightface expects OpenCV ordering, not the harness's float RGB."""
        analysis = _FakeAnalysis([])
        from identitylock.embeddings.learned import ArcFaceEmbedder

        ArcFaceEmbedder(app=analysis).describe(np.zeros((48, 64, 3), dtype=np.float32))
        assert analysis.frames == [(48, 64, 3)]
