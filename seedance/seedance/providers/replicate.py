"""Replicate.

Prices in line with the direct channel at 480p and 720p while taking a card
without a BytePlus account, which makes it the low-friction default. It reports
no token count, so its jobs bill at the estimate.

VERIFY before the first paid call: the input field names on the model page —
Replicate renames these between model versions more often than the price moves.
"""

from __future__ import annotations

from typing import Any

from seedance.models import JobSpec, JobStatus, ProviderStatus
from seedance.providers.base import (
    FatalProviderError,
    MissingCredentialError,
    PreparedRequest,
    Provider,
)

BASE_URL = "https://api.replicate.com/v1"
MODEL = "bytedance/seedance-2.5"

STATUS_MAP = {
    "starting": JobStatus.PENDING,
    "processing": JobStatus.RUNNING,
    "succeeded": JobStatus.SUCCEEDED,
    "failed": JobStatus.FAILED,
    "canceled": JobStatus.FAILED,
}


class ReplicateProvider(Provider):
    name = "replicate"
    rate_key = "replicate"

    @property
    def available(self) -> bool:
        return bool(self.settings.replicate_api_token)

    def _headers(self) -> dict[str, str]:
        if not self.available:
            raise MissingCredentialError(self.name, "REPLICATE_API_TOKEN")
        return {
            "Authorization": f"Bearer {self.settings.replicate_api_token}",
            "Content-Type": "application/json",
        }

    def prepare_submit(self, spec: JobSpec) -> PreparedRequest:
        payload: dict[str, Any] = {
            "prompt": spec.prompt,
            "resolution": spec.resolution.value,
            "duration": spec.duration_s,
            "aspect_ratio": spec.aspect_ratio,
            "fps": spec.fps,
            "audio": spec.audio,
            "camera_fixed": spec.camera_fixed,
        }
        if spec.seed is not None:
            payload["seed"] = spec.seed
        if spec.image_url:
            payload["image"] = spec.image_url
        if spec.reference_images:
            payload["reference_images"] = list(spec.reference_images)
        if spec.reference_video:
            payload["video"] = spec.reference_video

        return PreparedRequest(
            method="POST",
            url=f"{BASE_URL}/models/{MODEL}/predictions",
            headers=self._headers(),
            json={"input": payload},
        )

    def prepare_poll(self, task_id: str) -> PreparedRequest:
        return PreparedRequest(
            method="GET",
            url=f"{BASE_URL}/predictions/{task_id}",
            headers=self._headers(),
        )

    def parse_submit(self, payload: dict[str, Any]) -> str:
        task_id = payload.get("id")
        if not isinstance(task_id, str):
            raise FatalProviderError(f"Replicate reply carried no prediction id: {payload}")
        return task_id

    def parse_poll(self, payload: dict[str, Any]) -> ProviderStatus:
        status = STATUS_MAP.get(str(payload.get("status", "")).lower(), JobStatus.RUNNING)
        output = payload.get("output")
        video_url: str | None = None
        if isinstance(output, str):
            video_url = output
        elif isinstance(output, list) and output:
            video_url = str(output[-1])
        elif isinstance(output, dict):
            video_url = output.get("video") or output.get("url")
        return ProviderStatus(
            status=status,
            video_url=video_url,
            error=payload.get("error"),
            raw=payload,
        )
