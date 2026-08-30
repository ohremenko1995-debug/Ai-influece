"""Loading images into the one representation the rest of the code assumes.

Every downstream function takes ``Image``: float32, shape (H, W, 3), values in
[0, 1], sRGB, EXIF orientation already applied. Normalising once at the boundary
is why no metric has to ask what kind of array it was handed.
"""

from __future__ import annotations

import base64
import hashlib
import io
from pathlib import Path

import numpy as np
from numpy.typing import NDArray
from PIL import Image as PILImage
from PIL import ImageOps

Image = NDArray[np.float32]
"""float32 RGB, shape (H, W, 3), range [0, 1]."""

_CHUNK = 1 << 20


def sha256_file(path: Path) -> str:
    """Content hash of a file on disk, streamed so a 4K frame costs nothing."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def load_image(path: Path, *, max_side: int | None = 1024) -> Image:
    """Load and normalise one image.

    `max_side` bounds the long edge. Descriptors are computed on a fixed small
    grid anyway, so downscaling first is free accuracy-wise and keeps a batch of
    4K renders inside a sane memory budget.
    """
    with PILImage.open(path) as handle:
        oriented = ImageOps.exif_transpose(handle)
        rgb = (oriented or handle).convert("RGB")
        if max_side is not None and max(rgb.size) > max_side:
            scale = max_side / max(rgb.size)
            target = (max(1, round(rgb.width * scale)), max(1, round(rgb.height * scale)))
            rgb = rgb.resize(target, PILImage.Resampling.LANCZOS)
        array = np.asarray(rgb, dtype=np.float32) / 255.0
    return np.ascontiguousarray(array)


def save_image(image: Image, path: Path) -> None:
    """Write an ``Image`` back out as PNG, clamping rather than wrapping."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = np.clip(image, 0.0, 1.0)
    PILImage.fromarray((data * 255.0 + 0.5).astype(np.uint8), mode="RGB").save(path, format="PNG")


def thumbnail_data_uri(path: Path, *, size: int = 220, quality: int = 82) -> str:
    """A `data:` URI thumbnail, so an HTML report is one self-contained file.

    A report that points at image paths stops working the moment it is emailed.
    Inlining is the difference between an artefact and a broken link.
    """
    with PILImage.open(path) as handle:
        oriented = ImageOps.exif_transpose(handle)
        rgb = (oriented or handle).convert("RGB")
        rgb.thumbnail((size, size), PILImage.Resampling.LANCZOS)
        buffer = io.BytesIO()
        rgb.save(buffer, format="JPEG", quality=quality, optimize=True)
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/jpeg;base64,{encoded}"
