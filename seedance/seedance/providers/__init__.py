"""Adapter registry."""

from __future__ import annotations

from seedance.config import Settings
from seedance.providers.base import (
    FatalProviderError,
    MissingCredentialError,
    PreparedRequest,
    Provider,
    ProviderError,
    RetryableProviderError,
)
from seedance.providers.fake import FakeProvider
from seedance.providers.modelark import ModelArkProvider
from seedance.providers.replicate import ReplicateProvider
from seedance.providers.wavespeed import WaveSpeedProvider, WaveSpeedTurboProvider

PROVIDERS: dict[str, type[Provider]] = {
    ModelArkProvider.name: ModelArkProvider,
    ReplicateProvider.name: ReplicateProvider,
    WaveSpeedProvider.name: WaveSpeedProvider,
    WaveSpeedTurboProvider.name: WaveSpeedTurboProvider,
    FakeProvider.name: FakeProvider,
}


class UnknownAdapterError(RuntimeError):
    def __init__(self, name: str) -> None:
        super().__init__(
            f"no adapter for {name!r}. Adapters: {', '.join(sorted(PROVIDERS))}. "
            f"Other providers in rates.toml are priced for comparison only."
        )


def get_provider(name: str, settings: Settings) -> Provider:
    try:
        factory = PROVIDERS[name]
    except KeyError as exc:
        raise UnknownAdapterError(name) from exc
    return factory(settings)


__all__ = [
    "PROVIDERS",
    "FakeProvider",
    "FatalProviderError",
    "MissingCredentialError",
    "PreparedRequest",
    "Provider",
    "ProviderError",
    "RetryableProviderError",
    "UnknownAdapterError",
    "get_provider",
]
