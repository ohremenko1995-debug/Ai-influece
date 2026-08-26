"""An offline provider.

Generates a placeholder file instead of a video and charges nothing real, so the
whole pipeline — budget check, cache, queue, download, ledger — can be exercised
without an API key or a bill. Priced like the direct channel so the numbers the
tests assert on are the numbers production would produce.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx

from seedance.config import Settings
from seedance.models import JobSpec, JobStatus, ProviderStatus
from seedance.providers.base import PreparedRequest, Provider, RetryableProviderError

PLACEHOLDER = b"\x00\x00\x00\x18ftypmp42fake seedance output"


class FakeProvider(Provider):
    name = "fake"
    rate_key = "fake"

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self.submitted: list[JobSpec] = []
        #: Set by tests to make the first N submissions fail retryably.
        self.fail_first_n = 0
        self._dir = settings.output_dir / ".fake"

    @property
    def available(self) -> bool:
        return True

    def prepare_submit(self, spec: JobSpec) -> PreparedRequest:
        return PreparedRequest(
            method="POST",
            url="fake://generate",
            headers={"Authorization": "Bearer fake"},
            json={"prompt": spec.prompt, "resolution": spec.resolution.value},
        )

    def prepare_poll(self, task_id: str) -> PreparedRequest:
        return PreparedRequest(method="GET", url=f"fake://tasks/{task_id}")

    def parse_submit(self, payload: dict[str, Any]) -> str:
        return str(payload["id"])

    def parse_poll(self, payload: dict[str, Any]) -> ProviderStatus:
        return ProviderStatus(status=JobStatus.SUCCEEDED, video_url=str(payload["url"]))

    async def submit(self, client: httpx.AsyncClient, spec: JobSpec) -> str:  # noqa: ARG002
        if self.fail_first_n > 0:
            self.fail_first_n -= 1
            raise RetryableProviderError("fake provider was told to fail this attempt")
        self.submitted.append(spec)
        task_id = spec.fingerprint(self.name)
        # Blocking I/O in an async method, deliberately: this writes 30 bytes in
        # a test double, and threading it through anyio would only obscure that.
        self._dir.mkdir(parents=True, exist_ok=True)
        Path(self._dir / f"{task_id}.mp4").write_bytes(PLACEHOLDER)  # noqa: ASYNC240
        return task_id

    async def poll(self, client: httpx.AsyncClient, task_id: str) -> ProviderStatus:  # noqa: ARG002
        path = self._dir / f"{task_id}.mp4"
        return ProviderStatus(
            status=JobStatus.SUCCEEDED,
            video_url=path.resolve().as_uri(),
            tokens=None,
        )
