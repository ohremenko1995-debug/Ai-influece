"""BytePlus ModelArk — ByteDance's own international channel.

The cheapest route that is not a promo, and the one whose reply carries
`usage.completion_tokens`, i.e. the authoritative number of tokens you were
charged for. Everything else is a reseller of this.

Generation parameters ride as text commands appended to the prompt, which is how
the Ark video API has worked since Seedance 1.0.

VERIFY before the first paid call: the region host in `SEEDANCE_ARK_BASE_URL`,
the model id in rates.toml, and the exact flag spelling below. `seedance draft
--dry-run` prints the request so it can be curl'd against the docs.
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

STATUS_MAP = {
    "queued": JobStatus.PENDING,
    "running": JobStatus.RUNNING,
    "succeeded": JobStatus.SUCCEEDED,
    "failed": JobStatus.FAILED,
    "cancelled": JobStatus.FAILED,
}


class ModelArkProvider(Provider):
    name = "modelark"
    rate_key = "modelark"
    model_id = "dreamina-seedance-2-5-260628"

    @property
    def available(self) -> bool:
        return bool(self.settings.modelark_api_key)

    def _headers(self) -> dict[str, str]:
        if not self.available:
            raise MissingCredentialError(self.name, "ARK_API_KEY")
        return {
            "Authorization": f"Bearer {self.settings.modelark_api_key}",
            "Content-Type": "application/json",
        }

    @staticmethod
    def _command_suffix(spec: JobSpec) -> str:
        """The `--flag value` tail Ark parses out of the prompt text."""
        flags = [
            f"--resolution {spec.resolution.value}",
            f"--duration {spec.duration_s}",
            f"--ratio {spec.aspect_ratio}",
            f"--framepersecond {spec.fps}",
            "--watermark false",
        ]
        if spec.seed is not None:
            flags.append(f"--seed {spec.seed}")
        if spec.camera_fixed:
            flags.append("--camerafixed true")
        if not spec.audio:
            flags.append("--audio false")
        return " ".join(flags)

    def prepare_submit(self, spec: JobSpec) -> PreparedRequest:
        content: list[dict[str, Any]] = [
            {"type": "text", "text": f"{spec.prompt} {self._command_suffix(spec)}"}
        ]
        if spec.image_url:
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": spec.image_url},
                    "role": "first_frame",
                }
            )
        content.extend(
            {"type": "image_url", "image_url": {"url": url}, "role": "reference_image"}
            for url in spec.reference_images
        )
        if spec.reference_video:
            content.append({"type": "video_url", "video_url": {"url": spec.reference_video}})

        return PreparedRequest(
            method="POST",
            url=f"{self.settings.modelark_base_url}/contents/generations/tasks",
            headers=self._headers(),
            json={"model": self.model_id, "content": content},
        )

    def prepare_poll(self, task_id: str) -> PreparedRequest:
        return PreparedRequest(
            method="GET",
            url=f"{self.settings.modelark_base_url}/contents/generations/tasks/{task_id}",
            headers=self._headers(),
        )

    def parse_submit(self, payload: dict[str, Any]) -> str:
        task_id = payload.get("id")
        if not isinstance(task_id, str):
            raise FatalProviderError(f"ModelArk reply carried no task id: {payload}")
        return task_id

    def parse_poll(self, payload: dict[str, Any]) -> ProviderStatus:
        raw_status = str(payload.get("status", "")).lower()
        status = STATUS_MAP.get(raw_status, JobStatus.RUNNING)
        content = payload.get("content") or {}
        usage = payload.get("usage") or {}
        error = payload.get("error") or {}
        return ProviderStatus(
            status=status,
            video_url=content.get("video_url") if isinstance(content, dict) else None,
            # The charge signal: bill against this, not against the estimate.
            tokens=usage.get("completion_tokens") if isinstance(usage, dict) else None,
            error=error.get("message") if isinstance(error, dict) else None,
            raw=payload,
        )
