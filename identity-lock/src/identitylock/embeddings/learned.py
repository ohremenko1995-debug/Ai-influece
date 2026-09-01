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

from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Any

import numpy as np

from identitylock.embeddings.base import Descriptor, Vector, l2_normalise
from identitylock.embeddings.classical import ClassicalEmbedder, centre_crop
from identitylock.imaging.loader import Image

if TYPE_CHECKING:  # pragma: no cover - typing only
    pass


Encoder = Callable[[Image], Vector]


def describe_with(encode: Encoder, image: Image, *, identity_crop: float) -> Descriptor:
    """Route one frame through an image encoder into the two-vector contract.

    Identity is read from a centre crop, content from the whole frame. This lives
    outside the classes because the *routing* — not the model — is where a bug
    would silently swap the two vectors, and routing can be tested without any
    weights at all.
    """
    return Descriptor(
        identity=l2_normalise(encode(centre_crop(image, identity_crop))),
        content=l2_normalise(encode(image)),
    )


def select_largest_face(faces: Sequence[Any]) -> Any | None:
    """The biggest detected face by bounding-box area, or ``None`` if there is none.

    Separated out for the same reason: picking the wrong face, or picking one out
    of an empty list, is a real failure mode and needs a test that does not need a
    detector.
    """
    if not faces:
        return None

    def area(face: Any) -> float:
        box = np.asarray(face.bbox, dtype=np.float64)
        return float(max(box[2] - box[0], 0.0) * max(box[3] - box[1], 0.0))

    return max(faces, key=area)


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
        return describe_with(self._encode, image, identity_crop=self._identity_crop)


class ArcFaceEmbedder:
    """InsightFace face-recognition embedding for identity, classical for content.

    This is the backend the identity metrics were designed around: a 512-d
    embedding trained for verification, where cosine has a calibrated meaning and
    an impostor margin is the number the face-recognition literature reports.

    A frame with no detectable face cannot be verified at all. It is scored as a
    zero identity vector — the same dimension as every other frame, so the run does
    not crash, and a cosine of exactly 0.0, so the identity gate *rejects* it rather
    than accepting it against a different yardstick. The count is exposed as
    ``misses`` and travels into the run manifest, so a batch that failed detection
    rather than failing identity is distinguishable in the report.

    (An earlier version returned the classical descriptor here. That is 292-d
    against this backend's 512-d space, so the first undetectable face aborted the
    run with a broadcast error.)
    """

    def __init__(
        self,
        model_pack: str = "buffalo_l",
        *,
        det_size: int = 640,
        app: Any | None = None,
    ) -> None:
        """Build the backend.

        ``app`` accepts an already-prepared ``FaceAnalysis``. That lets a caller
        share one loaded model across embedders instead of paying the load twice —
        and it is what makes the detection paths testable without model weights.
        """
        if app is None:
            try:
                from insightface.app import FaceAnalysis
            except ImportError as error:  # pragma: no cover - depends on optional extra
                raise MissingBackendError("arcface", "insightface onnxruntime") from error

            app = FaceAnalysis(name=model_pack)
            app.prepare(ctx_id=-1, det_size=(det_size, det_size))

        self._app: Any = app
        self._fallback = ClassicalEmbedder()
        self.name = f"arcface:{model_pack}"
        self._identity_dim = 512
        self.misses = 0

    @property
    def identity_dim(self) -> int:
        return self._identity_dim

    def describe(self, image: Image) -> Descriptor:
        # One fallback pass, reused for both branches: the classical descriptor is
        # the content vector either way, and also the identity vector when no face
        # is found.
        fallback = self._fallback.describe(image)
        frame = (np.clip(image, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)[:, :, ::-1]
        largest = select_largest_face(self._app.get(frame))
        if largest is None:
            self.misses += 1
            return Descriptor(
                identity=np.zeros(self._identity_dim, dtype=np.float32),
                content=fallback.content,
            )
        return Descriptor(
            identity=l2_normalise(np.asarray(largest.normed_embedding, dtype=np.float32)),
            content=fallback.content,
        )
