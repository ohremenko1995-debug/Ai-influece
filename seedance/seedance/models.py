"""The internal job contract.

Every provider adapter speaks this shape. Nothing above the adapter layer knows
whether a job ends up at BytePlus, Replicate or WaveSpeed, which is the point:
list prices for this model move, and switching provider has to stay a config
change rather than a rewrite.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field, replace
from enum import StrEnum

#: Seedance 2.5 generates 4..30 s in one take. Duration bills linearly, so a
#: 30 s clip costs exactly six 5 s clips — length is never a discount.
MIN_DURATION_S = 1
MAX_DURATION_S = 30


class Resolution(StrEnum):
    """Output resolutions Seedance 2.5 bills for."""

    R480P = "480p"
    R720P = "720p"
    R1080P = "1080p"


class JobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class JobKind(StrEnum):
    """Which half of the draft/final pipeline a job belongs to."""

    DRAFT = "draft"
    FINAL = "final"
    ONE_OFF = "one_off"


@dataclass(frozen=True, slots=True)
class JobSpec:
    """What to generate, independent of who generates it.

    `audio` defaults on because Seedance bills nothing for it — there is no audio
    term in the rate matrix, so leaving it off saves zero and loses the soundtrack.
    """

    prompt: str
    resolution: Resolution = Resolution.R480P
    duration_s: int = 5
    aspect_ratio: str = "16:9"
    fps: int = 24
    seed: int | None = None
    image_url: str | None = None
    reference_images: tuple[str, ...] = ()
    reference_video: str | None = None
    reference_video_s: int = 0
    audio: bool = True
    camera_fixed: bool = False

    def __post_init__(self) -> None:
        if not self.prompt.strip():
            raise ValueError("prompt is empty")
        if not MIN_DURATION_S <= self.duration_s <= MAX_DURATION_S:
            raise ValueError(
                f"duration must be {MIN_DURATION_S}..{MAX_DURATION_S} s, got {self.duration_s}"
            )
        if self.fps <= 0:
            raise ValueError(f"fps must be positive, got {self.fps}")
        if self.reference_video and self.reference_video_s <= 0:
            # Input video duration is a term in the token formula. Priced as zero
            # it would under-estimate every reference-to-video job.
            raise ValueError("reference_video needs reference_video_s for costing")

    @property
    def has_video_input(self) -> bool:
        """Video input moves the job to the cheaper token rate."""
        return self.reference_video is not None

    def with_(self, **changes: object) -> JobSpec:
        """A copy with fields changed — used to lift a chosen draft to final."""
        return replace(self, **changes)  # type: ignore[arg-type]

    def fingerprint(self, provider: str) -> str:
        """Stable identity of "this exact generation on this exact provider".

        Used to serve a repeat request from disk instead of paying for it twice.
        The provider is part of the key because the same spec on another provider
        is a different bill and often a different file.
        """
        payload = json.dumps(
            {"provider": provider, **asdict(self)},
            sort_keys=True,
            ensure_ascii=False,
            default=str,
        )
        return hashlib.sha256(payload.encode()).hexdigest()[:32]


@dataclass(frozen=True, slots=True)
class CostEstimate:
    """What a job is expected to cost, and how that number was reached."""

    usd: float
    basis: str
    tokens: int | None = None
    detail: str = ""


@dataclass(slots=True)
class JobRecord:
    """A submitted job and everything the ledger knows about it."""

    id: str
    run_id: str
    kind: JobKind
    provider: str
    spec: JobSpec
    fingerprint: str
    status: JobStatus = JobStatus.PENDING
    estimated_usd: float = 0.0
    actual_usd: float | None = None
    tokens: int | None = None
    provider_task_id: str | None = None
    video_path: str | None = None
    error: str | None = None
    cached: bool = False
    created_at: str = ""

    @property
    def billed_usd(self) -> float:
        """Actual spend where the provider reported it, estimate otherwise."""
        return self.actual_usd if self.actual_usd is not None else self.estimated_usd


@dataclass(frozen=True, slots=True)
class ProviderStatus:
    """One poll of a provider-side task."""

    status: JobStatus
    video_url: str | None = None
    tokens: int | None = None
    error: str | None = None
    raw: dict[str, object] = field(default_factory=dict)
