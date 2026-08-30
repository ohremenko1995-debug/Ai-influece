"""A dependency-free image descriptor.

**Read this before trusting a number that came out of it.** This is a classical
computer-vision descriptor — oriented gradients, rotation-invariant LBP texture
and saturation-weighted hue histograms — not a learned face embedding. It is a
real, deterministic measurement of the pixels, and it separates characters whose
structure and palette differ. It will *not* tell two similar-looking people
apart the way ArcFace does.

It is the default for three reasons: it installs with numpy alone, it is
deterministic to the last bit across machines, and it makes the harness runnable
by anyone without a GPU. For production identity numbers, point the same
protocol at :mod:`identitylock.embeddings.learned`.

Every constant below is published in ``docs/metrics.md``.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray
from PIL import Image as PILImage

from identitylock.embeddings.base import Descriptor, Vector, l2_normalise
from identitylock.imaging.loader import Image
from identitylock.imaging.stats import luma

_IDENTITY_CROP = 0.50
"""Central fraction of the frame treated as the subject region.

Swept over {0.42, 0.50, 0.58, 0.62, 0.72} on the bundled four-character cohort;
0.50 maximised the impostor margin (mean 0.48, min 0.17) because a wider crop
lets the background — which is scene, not identity — into the hue histogram.
The sweep is reproducible with ``identitylock calibrate``."""

_IDENTITY_SIZE = 96
_CONTENT_SIZE = 96

_HOG_CELLS = 4
_HOG_BINS = 9
_HUE_TILES = 3
_HUE_BINS = 12
_LBP_TILES = 2
_LBP_BINS = 10

_CONTENT_LAYOUT_TILES = 6
_CONTENT_HUE_BINS = 16
_CONTENT_SAT_BINS = 8
_CONTENT_VAL_BINS = 8
_CONTENT_EDGE_TILES = 3

_IDENTITY_BLOCK_WEIGHTS = (0.55, 0.30, 0.15)
_SUBJECT_SIGMA = 0.55
"""Width of the radial subject weighting, in half-crop units."""
_CONTENT_BLOCK_WEIGHTS = (0.50, 0.30, 0.20)

_EPS = 1e-8


def _riu2_lut() -> NDArray[np.int64]:
    """Rotation-invariant uniform LBP mapping for P=8 (Ojala et al., 2002).

    Codes with at most two circular 0/1 transitions map to their popcount (0..8);
    everything else falls into a single "non-uniform" bin. Ten bins total, and
    the mapping is rotation invariant, so a tilted head does not read as a
    different texture.
    """
    lut = np.empty(256, dtype=np.int64)
    for code in range(256):
        bits = [(code >> index) & 1 for index in range(8)]
        transitions = sum(bits[index] != bits[(index + 1) % 8] for index in range(8))
        lut[code] = sum(bits) if transitions <= 2 else 9
    return lut


_RIU2 = _riu2_lut()


def _resize(image: Image, size: int) -> Image:
    """Resample to a square working grid so descriptors are resolution-independent."""
    pil = PILImage.fromarray((np.clip(image, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8), mode="RGB")
    resized = pil.resize((size, size), PILImage.Resampling.LANCZOS)
    return np.asarray(resized, dtype=np.float32) / 255.0


def _centre_crop(image: Image, fraction: float) -> Image:
    height, width = image.shape[0], image.shape[1]
    crop_h = max(1, round(height * fraction))
    crop_w = max(1, round(width * fraction))
    top = (height - crop_h) // 2
    left = (width - crop_w) // 2
    return np.ascontiguousarray(image[top : top + crop_h, left : left + crop_w])


def rgb_to_hsv(image: Image) -> Image:
    """Vectorised sRGB to HSV. Hue in [0, 1), saturation and value in [0, 1]."""
    red, green, blue = image[..., 0], image[..., 1], image[..., 2]
    maximum = np.max(image, axis=-1)
    minimum = np.min(image, axis=-1)
    span = maximum - minimum

    hue = np.zeros_like(maximum)
    safe = span > _EPS
    red_max = safe & (maximum == red)
    green_max = safe & (maximum == green) & ~red_max
    blue_max = safe & ~red_max & ~green_max

    with np.errstate(invalid="ignore", divide="ignore"):
        hue = np.where(red_max, ((green - blue) / np.where(safe, span, 1.0)) % 6.0, hue)
        hue = np.where(green_max, (blue - red) / np.where(safe, span, 1.0) + 2.0, hue)
        hue = np.where(blue_max, (red - green) / np.where(safe, span, 1.0) + 4.0, hue)
    hue = (hue / 6.0) % 1.0

    saturation = np.where(maximum > _EPS, span / np.where(maximum > _EPS, maximum, 1.0), 0.0)
    return np.asarray(np.stack([hue, saturation, maximum], axis=-1), dtype=np.float32)


def _gradients(gray: NDArray[np.float32]) -> tuple[NDArray[np.float32], NDArray[np.float32]]:
    """Central-difference gradients, returned as (magnitude, unsigned orientation)."""
    gx = np.zeros_like(gray)
    gy = np.zeros_like(gray)
    gx[:, 1:-1] = gray[:, 2:] - gray[:, :-2]
    gy[1:-1, :] = gray[2:, :] - gray[:-2, :]
    magnitude = np.hypot(gx, gy).astype(np.float32)
    orientation = np.mod(np.arctan2(gy, gx), np.pi).astype(np.float32)
    return magnitude, orientation


def _tiles(size: int, count: int) -> list[tuple[int, int]]:
    """Tile boundaries that cover the grid exactly, even when it does not divide."""
    edges = [round(index * size / count) for index in range(count + 1)]
    return [(edges[index], edges[index + 1]) for index in range(count)]


def _radial_weight(size: int, sigma: float) -> NDArray[np.float32]:
    """Gaussian falloff from the centre of the crop.

    The subject sits in the middle; the corners are backdrop. Weighting pixel
    votes by distance from the centre is a cheap, explicit stand-in for the
    segmentation mask a production pipeline would use, and it is what stops a
    change of background from reading as a change of person.
    """
    axis = np.linspace(-1.0, 1.0, size, dtype=np.float32)
    xs, ys = np.meshgrid(axis, axis)
    return np.asarray(np.exp(-(xs**2 + ys**2) / (2.0 * sigma**2)), dtype=np.float32)


def _hog(
    gray: NDArray[np.float32], cells: int, bins: int, weight: NDArray[np.float32] | None = None
) -> Vector:
    """Magnitude-weighted orientation histogram per cell, each cell L2-normalised.

    Hard orientation binning, not the trilinear interpolation of the original HOG:
    the grid here is coarse (4x4 cells over 96px) and the interpolation buys
    precision the downstream cosine cannot use.
    """
    magnitude, orientation = _gradients(gray)
    if weight is not None:
        magnitude = magnitude * weight
    index = np.clip((orientation / np.pi * bins).astype(np.int64), 0, bins - 1)
    rows = _tiles(gray.shape[0], cells)
    cols = _tiles(gray.shape[1], cells)

    blocks: list[Vector] = []
    for top, bottom in rows:
        for left, right in cols:
            cell_index = index[top:bottom, left:right].ravel()
            cell_weight = magnitude[top:bottom, left:right].ravel()
            histogram = np.bincount(cell_index, weights=cell_weight, minlength=bins)
            blocks.append(l2_normalise(histogram.astype(np.float32)))
    return np.concatenate(blocks) if blocks else np.zeros(0, dtype=np.float32)


def _hue_histogram(
    hsv: Image, tiles: int, bins: int, weight: NDArray[np.float32] | None = None
) -> Vector:
    """Hue histogram per tile, weighted by saturation x value.

    Weighting matters: the hue of a near-grey or near-black pixel is numerically
    defined but visually meaningless, and letting it vote adds pure noise.
    """
    hue, saturation, value = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    votes = (saturation * value).astype(np.float32)
    if weight is not None:
        votes = votes * weight
    index = np.clip((hue * bins).astype(np.int64), 0, bins - 1)
    rows = _tiles(hsv.shape[0], tiles)
    cols = _tiles(hsv.shape[1], tiles)

    blocks: list[Vector] = []
    for top, bottom in rows:
        for left, right in cols:
            histogram = np.bincount(
                index[top:bottom, left:right].ravel(),
                weights=votes[top:bottom, left:right].ravel(),
                minlength=bins,
            )
            blocks.append(l2_normalise(histogram.astype(np.float32)))
    return np.concatenate(blocks) if blocks else np.zeros(0, dtype=np.float32)


def _lbp_histogram(gray: NDArray[np.float32], tiles: int) -> Vector:
    """Rotation-invariant uniform LBP histogram per tile."""
    if gray.shape[0] < 3 or gray.shape[1] < 3:
        return np.zeros(tiles * tiles * _LBP_BINS, dtype=np.float32)

    centre = gray[1:-1, 1:-1]
    neighbours = (
        gray[:-2, :-2],
        gray[:-2, 1:-1],
        gray[:-2, 2:],
        gray[1:-1, 2:],
        gray[2:, 2:],
        gray[2:, 1:-1],
        gray[2:, :-2],
        gray[1:-1, :-2],
    )
    code = np.zeros(centre.shape, dtype=np.int64)
    for shift, neighbour in enumerate(neighbours):
        code |= (neighbour >= centre).astype(np.int64) << shift
    labels = _RIU2[code]

    rows = _tiles(labels.shape[0], tiles)
    cols = _tiles(labels.shape[1], tiles)
    blocks: list[Vector] = []
    for top, bottom in rows:
        for left, right in cols:
            histogram = np.bincount(labels[top:bottom, left:right].ravel(), minlength=_LBP_BINS)
            blocks.append(l2_normalise(histogram.astype(np.float32)))
    return np.concatenate(blocks) if blocks else np.zeros(0, dtype=np.float32)


def _layout(gray: NDArray[np.float32], tiles: int) -> Vector:
    """Mean luminance per tile — where the light and the subject sit in the frame."""
    rows = _tiles(gray.shape[0], tiles)
    cols = _tiles(gray.shape[1], tiles)
    values = [
        float(np.mean(gray[top:bottom, left:right])) for top, bottom in rows for left, right in cols
    ]
    return l2_normalise(np.asarray(values, dtype=np.float32))


def _palette(hsv: Image) -> Vector:
    """Global hue / saturation / value histograms concatenated."""
    hue, saturation, value = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    weight = (saturation * value).astype(np.float32).ravel()
    hue_hist = np.bincount(
        np.clip((hue.ravel() * _CONTENT_HUE_BINS).astype(np.int64), 0, _CONTENT_HUE_BINS - 1),
        weights=weight,
        minlength=_CONTENT_HUE_BINS,
    )
    sat_hist = np.bincount(
        np.clip(
            (saturation.ravel() * _CONTENT_SAT_BINS).astype(np.int64), 0, _CONTENT_SAT_BINS - 1
        ),
        minlength=_CONTENT_SAT_BINS,
    )
    val_hist = np.bincount(
        np.clip((value.ravel() * _CONTENT_VAL_BINS).astype(np.int64), 0, _CONTENT_VAL_BINS - 1),
        minlength=_CONTENT_VAL_BINS,
    )
    return np.concatenate(
        [
            l2_normalise(hue_hist.astype(np.float32)),
            l2_normalise(sat_hist.astype(np.float32)),
            l2_normalise(val_hist.astype(np.float32)),
        ]
    )


def _edge_density(gray: NDArray[np.float32], tiles: int) -> Vector:
    """Mean gradient magnitude per tile — busy background versus clean backdrop."""
    magnitude, _ = _gradients(gray)
    rows = _tiles(gray.shape[0], tiles)
    cols = _tiles(gray.shape[1], tiles)
    values = [
        float(np.mean(magnitude[top:bottom, left:right]))
        for top, bottom in rows
        for left, right in cols
    ]
    return l2_normalise(np.asarray(values, dtype=np.float32))


def _weighted_concat(blocks: tuple[Vector, ...], weights: tuple[float, ...]) -> Vector:
    """Concatenate already-normalised blocks under fixed weights, then renormalise.

    Without per-block normalisation the longest histogram would dominate the
    cosine purely because it has more bins. The weights are a stated editorial
    choice about what identity means here, not a fitted parameter.
    """
    scaled = [block * weight for block, weight in zip(blocks, weights, strict=True)]
    return l2_normalise(np.concatenate(scaled).astype(np.float32))


class ClassicalEmbedder:
    """Deterministic gradient / texture / colour descriptor. No model weights."""

    name = "classical-v1"

    def __init__(
        self,
        *,
        identity_crop: float = _IDENTITY_CROP,
        block_weights: tuple[float, float, float] = _IDENTITY_BLOCK_WEIGHTS,
        subject_sigma: float | None = _SUBJECT_SIGMA,
    ) -> None:
        if not 0.1 <= identity_crop <= 1.0:
            raise ValueError("identity_crop must lie in [0.1, 1.0]")
        if len(block_weights) != 3 or any(weight < 0.0 for weight in block_weights):
            raise ValueError("block_weights must be three non-negative numbers")
        self._identity_crop = identity_crop
        self._block_weights = block_weights
        self._subject = (
            None if subject_sigma is None else _radial_weight(_IDENTITY_SIZE, subject_sigma)
        )
        self._identity_dim = len(self.describe(np.zeros((8, 8, 3), dtype=np.float32)).identity)

    @property
    def identity_dim(self) -> int:
        return self._identity_dim

    def describe(self, image: Image) -> Descriptor:
        subject = _resize(_centre_crop(image, self._identity_crop), _IDENTITY_SIZE)
        subject_gray = luma(subject)
        subject_hsv = rgb_to_hsv(subject)

        identity = _weighted_concat(
            (
                _hog(subject_gray, _HOG_CELLS, _HOG_BINS, self._subject),
                _hue_histogram(subject_hsv, _HUE_TILES, _HUE_BINS, self._subject),
                _lbp_histogram(subject_gray, _LBP_TILES),
            ),
            self._block_weights,
        )

        scene = _resize(image, _CONTENT_SIZE)
        scene_gray = luma(scene)
        content = _weighted_concat(
            (
                _layout(scene_gray, _CONTENT_LAYOUT_TILES),
                _palette(rgb_to_hsv(scene)),
                _edge_density(scene_gray, _CONTENT_EDGE_TILES),
            ),
            _CONTENT_BLOCK_WEIGHTS,
        )

        return Descriptor(identity=identity, content=content)
