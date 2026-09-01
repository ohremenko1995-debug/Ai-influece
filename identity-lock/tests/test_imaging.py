"""Pixel measurements, checked against cases whose answers are known in advance."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PIL import Image as PILImage
from PIL import ImageFilter

from identitylock.imaging.loader import load_image, save_image, sha256_file, thumbnail_data_uri
from identitylock.imaging.stats import (
    clipping,
    colorfulness,
    contrast,
    entropy,
    exposure,
    frame_stats,
    laplacian,
    sharpness,
    technical_score,
)


def _write(path: Path, array: np.ndarray) -> Path:
    PILImage.fromarray((np.clip(array, 0, 1) * 255).astype(np.uint8), "RGB").save(path)
    return path


@pytest.fixture
def noise() -> np.ndarray:
    rng = np.random.default_rng(11)
    return rng.random((64, 64, 3)).astype(np.float32)


class TestLoader:
    def test_normalises_to_float_rgb(self, tmp_path: Path, noise: np.ndarray) -> None:
        image = load_image(_write(tmp_path / "a.png", noise))
        assert image.dtype == np.float32
        assert image.shape == (64, 64, 3)
        assert float(image.min()) >= 0.0 and float(image.max()) <= 1.0

    def test_converts_greyscale_to_three_channels(self, tmp_path: Path) -> None:
        path = tmp_path / "grey.png"
        PILImage.fromarray(np.full((16, 16), 128, dtype=np.uint8), "L").save(path)
        assert load_image(path).shape == (16, 16, 3)

    def test_bounds_the_long_edge(self, tmp_path: Path) -> None:
        rng = np.random.default_rng(3)
        path = _write(tmp_path / "big.png", rng.random((400, 200, 3)))
        assert max(load_image(path, max_side=100).shape[:2]) == 100

    def test_leaves_small_images_alone(self, tmp_path: Path, noise: np.ndarray) -> None:
        assert load_image(_write(tmp_path / "a.png", noise), max_side=512).shape[0] == 64

    def test_round_trips_through_save(self, tmp_path: Path, noise: np.ndarray) -> None:
        save_image(noise, tmp_path / "out" / "b.png")
        reloaded = load_image(tmp_path / "out" / "b.png")
        assert np.allclose(reloaded, noise, atol=1.5 / 255)

    def test_hashes_content_not_names(self, tmp_path: Path, noise: np.ndarray) -> None:
        first = _write(tmp_path / "one.png", noise)
        second = _write(tmp_path / "two.png", noise)
        assert sha256_file(first) == sha256_file(second)

    def test_thumbnail_is_a_data_uri(self, tmp_path: Path, noise: np.ndarray) -> None:
        uri = thumbnail_data_uri(_write(tmp_path / "a.png", noise), size=32)
        assert uri.startswith("data:image/jpeg;base64,")
        assert len(uri) > 100


class TestLaplacian:
    def test_is_zero_on_a_flat_field(self) -> None:
        assert float(np.abs(laplacian(np.full((10, 10), 0.5, dtype=np.float32))).max()) == 0.0

    def test_is_zero_on_a_linear_ramp(self) -> None:
        """A linear gradient has no second derivative; a focus measure must ignore it."""
        ramp = np.tile(np.linspace(0, 1, 12, dtype=np.float32), (12, 1))
        assert float(np.abs(laplacian(ramp)).max()) < 1e-6

    def test_handles_images_too_small_to_convolve(self) -> None:
        assert laplacian(np.zeros((2, 2), dtype=np.float32)).size == 0


class TestStats:
    def test_sharpness_orders_blur_correctly(self) -> None:
        """A real Gaussian blur, not a nearest-neighbour upscale: block artefacts
        are themselves hard edges and would score as sharp."""
        rng = np.random.default_rng(5)
        detailed = np.clip(
            0.5
            + 0.25 * np.sin(np.linspace(0, 40, 96))[None, :, None]
            + 0.05 * rng.normal(size=(96, 96, 3)),
            0,
            1,
        ).astype(np.float32)
        pil = PILImage.fromarray((detailed * 255).astype(np.uint8), "RGB")
        blurred = (
            np.asarray(pil.filter(ImageFilter.GaussianBlur(radius=4)), dtype=np.float32) / 255.0
        )
        assert sharpness(detailed) > sharpness(blurred)

    def test_exposure_peaks_at_mid_grey(self) -> None:
        mid = np.full((8, 8, 3), 0.5, dtype=np.float32)
        dark = np.full((8, 8, 3), 0.05, dtype=np.float32)
        assert exposure(mid) == pytest.approx(1.0, abs=1e-6)
        assert exposure(dark) < 0.1

    def test_contrast_is_zero_on_a_flat_field(self) -> None:
        assert contrast(np.full((8, 8, 3), 0.5, dtype=np.float32)) == 0.0

    def test_colorfulness_separates_grey_from_colour(self) -> None:
        grey = np.full((8, 8, 3), 0.5, dtype=np.float32)
        colourful = np.zeros((8, 8, 3), dtype=np.float32)
        colourful[..., 0] = 1.0
        colourful[:4, :, 2] = 1.0
        assert colorfulness(grey) == 0.0
        assert colorfulness(colourful) > 0.5

    def test_clipping_counts_both_ends(self) -> None:
        image = np.full((10, 10, 3), 0.5, dtype=np.float32)
        image[:1] = 0.0
        image[9:] = 1.0
        assert clipping(image) == pytest.approx(0.2, abs=1e-6)

    def test_entropy_is_zero_for_one_value_and_never_negative(self) -> None:
        assert entropy(np.full((8, 8, 3), 0.5, dtype=np.float32)) == 0.0

    def test_every_score_is_in_range(self, noise: np.ndarray) -> None:
        stats = frame_stats(noise)
        for value in (stats.sharpness, stats.exposure, stats.contrast, stats.colorfulness):
            assert 0.0 <= value <= 1.0
        assert 0.0 <= technical_score(stats) <= 1.0

    def test_technical_score_prefers_the_better_frame(self, noise: np.ndarray) -> None:
        flat = np.full((64, 64, 3), 0.5, dtype=np.float32)
        assert technical_score(frame_stats(noise)) > technical_score(frame_stats(flat))

    def test_clipping_drags_the_composite_down(self) -> None:
        clean = np.clip(np.tile(np.linspace(0.2, 0.8, 64, dtype=np.float32), (64, 1)), 0, 1)
        clean_rgb = np.stack([clean] * 3, axis=-1)
        blown = np.clip(clean_rgb * 3.0, 0, 1)
        assert technical_score(frame_stats(blown)) < technical_score(frame_stats(clean_rgb))
