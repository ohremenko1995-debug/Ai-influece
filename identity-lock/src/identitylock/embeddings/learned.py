"""Learned backends, behind the same protocol.

These are the ones you want for production identity numbers. They are **not
exercised in this repository's CI** — the container has no GPU and no model
weights — so they are written to be small, obvious and easy to audit rather than
clever. The point of this module is that swapping the descriptor is a
one-word change (``--embedder arcface``), not a rewrite of the metric layer.

Install what a backend needs before selecting it::

    pip install open_clip_torch torch      # --embedder clip
    pip install insightface onnxruntime    # --embedder arcface
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np

from identitylock.embeddings.base import Descriptor, l2_normalise
from identitylock.embeddings.classical import ClassicalEmbedder, _centre_crop
from identitylock.imaging.loader import Image

if TYPE_CHECKING:  # pragma: no cover - typing only
    pass


class MissingBackendError(RuntimeError):
    """Raised when a backend is selected but its dependency is not installed."""

    def __init__(self, backend: str, package: str) -> None:
        super().__init__(
            f"The '{backend}' embedder needs the '{package}' package. "
            f"Install it with: pip install {package}"
        )


class ClipEmbedder:
    """OpenCLIP image tower.

    Identity is read from a centre crop and content from the whole frame, so the
    two vectors keep the meanings the metric layer expects: "who is in the middle"
    versus "what does the picture look like".

    CLIP is a semantic embedding, not a face-verification one. It is a strong
    same-character signal for stylised or full-body work and a weaker one for
    two similar faces — for the latter use :class:`ArcFaceEmbedder`.
    """

    def __init__(
        self,
        model_name: str = "ViT-B-32",
        pretrained: str = "laion2b_s34b_b79k",
        *,
        device: str = "cpu",
        identity_crop: float = 0.50,
    ) -> None:
        try:
            import open_clip
            import torch
        except ImportError as error:  # pragma: no cover - depends on optional extra
            raise MissingBackendError("clip", "open_clip_torch torch") from error

        self._torch = torch
        self._model, _, self._preprocess = open_clip.create_model_and_transforms(
            model_name, pretrained=pretrained, device=device
        )
        self._model.eval()
        self._device = device
        self._identity_crop = identity_crop
        self.name = f"clip:{model_name}/{pretrained}"
        self._identity_dim = int(self._model.visual.output_dim)

    @property
    def identity_dim(self) -> int:
        return self._identity_dim

    def _encode(self, image: Image) -> np.ndarray:
        from PIL import Image as PILImage

        pil = PILImage.fromarray((np.clip(image, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8), "RGB")
        tensor = self._preprocess(pil).unsqueeze(0).to(self._device)
        with self._torch.no_grad():
            features = self._model.encode_image(tensor)
        return np.asarray(features.cpu().numpy()[0], dtype=np.float32)

    def describe(self, image: Image) -> Descriptor:
        return Descriptor(
            identity=l2_normalise(self._encode(_centre_crop(image, self._identity_crop))),
            content=l2_normalise(self._encode(image)),
        )


class ArcFaceEmbedder:
    """InsightFace face-recognition embedding for identity, classical for content.

    This is the backend the identity metrics were designed around: a 512-d
    embedding trained for verification, where cosine has a calibrated meaning and
    an impostor margin is the number the face-recognition literature reports.

    Frames with no detectable face fall back to the classical identity descriptor
    and are flagged, because silently scoring a faceless frame as "identity 0.0"
    would poison the batch statistics with a detection failure.
    """

    def __init__(self, model_pack: str = "buffalo_l", *, det_size: int = 640) -> None:
        try:
            from insightface.app import FaceAnalysis
        except ImportError as error:  # pragma: no cover - depends on optional extra
            raise MissingBackendError("arcface", "insightface onnxruntime") from error

        self._app: Any = FaceAnalysis(name=model_pack)
        self._app.prepare(ctx_id=-1, det_size=(det_size, det_size))
        self._fallback = ClassicalEmbedder()
        self.name = f"arcface:{model_pack}"
        self._identity_dim = 512
        self.misses = 0

    @property
    def identity_dim(self) -> int:
        return self._identity_dim

    def describe(self, image: Image) -> Descriptor:
        content = self._fallback.describe(image).content
        frame = (np.clip(image, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)[:, :, ::-1]
        faces = self._app.get(frame)
        if not faces:
            self.misses += 1
            return Descriptor(identity=self._fallback.describe(image).identity, content=content)
        largest = max(faces, key=lambda face: float(np.prod(face.bbox[2:] - face.bbox[:2])))
        return Descriptor(
            identity=l2_normalise(np.asarray(largest.normed_embedding, dtype=np.float32)),
            content=content,
        )
