"""Technical frame measurements.

Every score returned here is in [0, 1] and higher is better, so the composite is
a plain weighted mean with no sign juggling. The raw physical quantity and the
squashing function used to map it into [0, 1] are both written down in
``docs/metrics.md`` — a score whose formula is not published is a vibe, not a
metric.
"""

from __future__ import annotations

import numpy as np

from identitylock.domain.models import FrameStats
from identitylock.imaging.loader import Image

# Squashing constants. Calibrated on the bundled synthetic cohort; see
# docs/evaluation-protocol.md for how to re-fit them to a real render set.
_SHARPNESS_TAU = 1.5e-3
_EXPOSURE_SIGMA = 0.18
_CONTRAST_REF = 0.25
_COLORFULNESS_REF = 0.30
_CLIPPING_REF = 0.02

_LUMA = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)

_TECHNICAL_WEIGHTS = {
    "sharpness": 0.40,
    "exposure": 0.25,
    "contrast": 0.20,
    "headroom": 0.15,
}


def luma(image: Image) -> np.ndarray:
    """Rec. 709 luminance."""
    return np.asarray(image @ _LUMA, dtype=np.float32)


def laplacian(channel: np.ndarray) -> np.ndarray:
    """4-neighbour discrete Laplacian on the interior, no padding artefacts.

    Written with slices rather than a convolution import: it is three lines, it
    is exact, and it keeps the dependency list at numpy.
    """
    if channel.shape[0] < 3 or channel.shape[1] < 3:
        return np.zeros((0, 0), dtype=np.float32)
    centre = channel[1:-1, 1:-1]
    return np.asarray(
        channel[:-2, 1:-1]
        + channel[2:, 1:-1]
        + channel[1:-1, :-2]
        + channel[1:-1, 2:]
        - 4.0 * centre,
        dtype=np.float32,
    )


def sharpness(image: Image) -> float:
    """Variance of the Laplacian, squashed by ``1 - exp(-v / tau)``.

    Variance of the Laplacian is the standard no-reference focus measure. It is
    unbounded and scale-dependent, so it is squashed rather than clipped: a
    saturating curve keeps very sharp frames distinguishable from merely sharp
    ones instead of flattening everything above the threshold to 1.0.
    """
    edges = laplacian(luma(image))
    if edges.size == 0:
        return 0.0
    variance = float(np.var(edges))
    return float(1.0 - np.exp(-variance / _SHARPNESS_TAU))


def exposure(image: Image) -> float:
    """Gaussian centred on mid-grey: 1.0 at mean luma 0.5, falling off both ways."""
    mean = float(np.mean(luma(image)))
    return float(np.exp(-((mean - 0.5) ** 2) / (2.0 * _EXPOSURE_SIGMA**2)))


def contrast(image: Image) -> float:
    """Luma standard deviation against a reference spread, clipped at 1.0."""
    return float(np.clip(float(np.std(luma(image))) / _CONTRAST_REF, 0.0, 1.0))


def colorfulness(image: Image) -> float:
    """Hasler & Süsstrunk (2003) colourfulness, normalised.

    Reported but deliberately *excluded* from the composite: a colourful frame is
    not a better frame, it is a different frame. It belongs in the report so a
    reviewer can spot a palette shift, not in a quality gate.
    """
    red, green, blue = image[..., 0], image[..., 1], image[..., 2]
    rg = red - green
    yb = 0.5 * (red + green) - blue
    std = float(np.hypot(np.std(rg), np.std(yb)))
    mean = float(np.hypot(np.mean(rg), np.mean(yb)))
    return float(np.clip((std + 0.3 * mean) / _COLORFULNESS_REF, 0.0, 1.0))


def clipping(image: Image) -> float:
    """Fraction of pixels crushed to black or blown to white."""
    crushed = float(np.mean(image <= 1.0 / 255.0))
    blown = float(np.mean(image >= 254.0 / 255.0))
    return crushed + blown


def entropy(image: Image) -> float:
    """Shannon entropy of the 64-bin luma histogram, normalised to [0, 1]."""
    histogram, _ = np.histogram(luma(image), bins=64, range=(0.0, 1.0))
    total = float(histogram.sum())
    if total <= 0.0:
        return 0.0
    probabilities = histogram.astype(np.float64) / total
    nonzero = probabilities[probabilities > 0.0]
    return max(0.0, float(-np.sum(nonzero * np.log2(nonzero)) / 6.0))


def frame_stats(image: Image) -> FrameStats:
    """All frame measurements in one pass over the array."""
    height, width = image.shape[0], image.shape[1]
    return FrameStats(
        width=int(width),
        height=int(height),
        sharpness=round(sharpness(image), 6),
        exposure=round(exposure(image), 6),
        contrast=round(contrast(image), 6),
        colorfulness=round(colorfulness(image), 6),
        clipping=round(clipping(image), 6),
        entropy=round(entropy(image), 6),
    )


def technical_score(stats: FrameStats) -> float:
    """Weighted composite of the measurements that a bad render actually fails.

    Clipping enters as *headroom* (``1 - clip/ref``) so that every term points the
    same way. Weights are in ``_TECHNICAL_WEIGHTS`` and sum to 1.0.
    """
    headroom = float(np.clip(1.0 - stats.clipping / _CLIPPING_REF, 0.0, 1.0))
    parts = {
        "sharpness": stats.sharpness,
        "exposure": stats.exposure,
        "contrast": stats.contrast,
        "headroom": headroom,
    }
    total = sum(_TECHNICAL_WEIGHTS[key] * value for key, value in parts.items())
    return round(float(total), 6)
