"""WaveSpeed, including the Turbo variant.

Turbo carries the cheapest published 720p rate of any route, and it is a
separate model id rather than a flag — hence two adapter instances over one
implementation.

VERIFY before the first paid call: the endpoint slug per variant, and whether
Turbo output is acceptable for your material. It is a different model, not a
discount on the same one.
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

BASE_URL = "https://api.wavespeed.ai/api/v3"

STATUS_MAP = {
    "created": JobStatus.PENDING,
    "processing": JobStatus.RUNNING,
    "completed": JobStatus.SUCCEEDED,
    "failed": JobStatus.FAILED,
}


class WaveSpeedProvider(Provider):
    name = "wavespeed"
    rate_key = "wavespeed"
    model_slug = "bytedance/seedance-2.5"

    @property
    def available(self) -> bool:
        return bool(self.settings.wavespeed_api_key)

    def _headers(self) -> dict[str, str]:
        if not self.available:
            raise MissingCredentialError(self.name, "WAVESPEED_API_KEY")
        return {
            "Authorization": f"Bearer {self.settings.wavespeed_api_key}",
            "Content-Type": "application/json",
        }

    def _endpoint(self, spec: JobSpec) -> str:
        if spec.reference_video or spec.reference_images:
            return "reference-to-video"
        return "image-to-video" if spec.image_url else "text-to-video"

    def prepare_submit(self, spec: JobSpec) -> PreparedRequest:
        payload: dict[str, Any] = {
            "prompt": spec.prompt,
            "resolution": spec.resolution.value,
            "duration": spec.duration_s,
            "aspect_ratio": spec.aspect_ratio,
            "enable_audio": spec.audio,
        }
        if spec.seed is not None:
            payload["seed"] = spec.seed
        if spec.image_url:
            payload["image"] = spec.image_url
        if spec.reference_images:
            payload["images"] = list(spec.reference_images)
        if spec.reference_video:
            payload["video"] = spec.reference_video

        return PreparedRequest(
            method="POST",
            url=f"{BASE_URL}/{self.model_slug}/{self._endpoint(spec)}",
            headers=self._headers(),
            json=payload,
        )

    def prepare_poll(self, task_id: str) -> PreparedRequest:
        return PreparedRequest(
            method="GET",
            url=f"{BASE_URL}/predictions/{task_id}/result",
            headers=self._headers(),
        )

    @staticmethod
    def _data(payload: dict[str, Any]) -> dict[str, Any]:
        data = payload.get("data")
        return data if isinstance(data, dict) else payload

    def parse_submit(self, payload: dict[str, Any]) -> str:
        task_id = self._data(payload).get("id")
        if not isinstance(task_id, str):
            raise FatalProviderError(f"WaveSpeed reply carried no task id: {payload}")
        return task_id

    def parse_poll(self, payload: dict[str, Any]) -> ProviderStatus:
        data = self._data(payload)
        status = STATUS_MAP.get(str(data.get("status", "")).lower(), JobStatus.RUNNING)
        outputs = data.get("outputs")
        video_url = str(outputs[0]) if isinstance(outputs, list) and outputs else None
        return ProviderStatus(
            status=status,
            video_url=video_url,
            error=data.get("error") or None,
            raw=payload,
        )


class WaveSpeedTurboProvider(WaveSpeedProvider):
    """The cheap variant. Same wire protocol, different model id and price."""

    name = "wavespeed_turbo"
    rate_key = "wavespeed_turbo"
    model_slug = "bytedance/seedance-2.5-turbo"
