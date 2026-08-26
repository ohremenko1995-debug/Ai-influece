"""The adapter contract.

Every adapter turns a `JobSpec` into an HTTP request and a provider reply back
into a `ProviderStatus`. Two rules keep this layer honest:

* The wire format lives in one place per adapter — `prepare_submit` — and both
  the real call and `--dry-run` go through it. What you inspect is what is sent.
* Anything the caller can retry (429, 5xx, a dropped connection) raises
  `RetryableProviderError`; anything that will fail again the same way (bad key,
  rejected prompt) raises `FatalProviderError`. The runner needs that difference
  to avoid burning a budget on a request that can never succeed.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import httpx

from seedance.config import Settings
from seedance.models import JobSpec, ProviderStatus

RETRYABLE_STATUS = frozenset({408, 409, 425, 429, 500, 502, 503, 504})


class ProviderError(RuntimeError):
    """Base class for adapter failures."""


class RetryableProviderError(ProviderError):
    """Worth trying again after a backoff."""


class FatalProviderError(ProviderError):
    """Will fail again identically; do not spend another attempt on it."""


class MissingCredentialError(FatalProviderError):
    def __init__(self, provider: str, env_var: str) -> None:
        super().__init__(f"{provider} needs {env_var} in the environment or .env")


@dataclass(frozen=True, slots=True)
class PreparedRequest:
    """A request about to go out, in a form that can also just be printed."""

    method: str
    url: str
    headers: dict[str, str] = field(default_factory=dict)
    json: dict[str, Any] | None = None

    def redacted(self) -> PreparedRequest:
        """The same request with credentials masked, safe to show or log."""
        safe = {
            key: ("***" if key.lower() in {"authorization", "x-api-key"} else value)
            for key, value in self.headers.items()
        }
        return PreparedRequest(self.method, self.url, safe, self.json)


def raise_for_status(response: httpx.Response, provider: str) -> None:
    """Translate an HTTP error into the retryable/fatal split."""
    if response.is_success:
        return
    body = response.text[:500]
    message = f"{provider} returned {response.status_code}: {body}"
    if response.status_code in RETRYABLE_STATUS:
        raise RetryableProviderError(message)
    raise FatalProviderError(message)


class Provider(ABC):
    """One video generation backend."""

    name: str
    #: Which rates.toml entry prices this adapter.
    rate_key: str

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @property
    @abstractmethod
    def available(self) -> bool:
        """Whether credentials for this provider are present."""

    @abstractmethod
    def prepare_submit(self, spec: JobSpec) -> PreparedRequest:
        """Build the create-task request."""

    @abstractmethod
    def prepare_poll(self, task_id: str) -> PreparedRequest:
        """Build the read-task request."""

    @abstractmethod
    def parse_submit(self, payload: dict[str, Any]) -> str:
        """Pull the provider-side task id out of a create-task reply."""

    @abstractmethod
    def parse_poll(self, payload: dict[str, Any]) -> ProviderStatus:
        """Turn a read-task reply into a status."""

    async def submit(self, client: httpx.AsyncClient, spec: JobSpec) -> str:
        request = self.prepare_submit(spec)
        response = await client.request(
            request.method, request.url, headers=request.headers, json=request.json
        )
        raise_for_status(response, self.name)
        return self.parse_submit(response.json())

    async def poll(self, client: httpx.AsyncClient, task_id: str) -> ProviderStatus:
        request = self.prepare_poll(task_id)
        response = await client.request(request.method, request.url, headers=request.headers)
        raise_for_status(response, self.name)
        return self.parse_poll(response.json())
