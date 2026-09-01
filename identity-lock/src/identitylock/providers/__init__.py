"""Generation backends. The evaluation layer knows this protocol and nothing else."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from identitylock.providers.base import (
    GenerationProvider,
    GenerationRequest,
    ProviderError,
)
from identitylock.providers.directory import DirectoryProvider
from identitylock.providers.synthetic import Scene, SyntheticProvider, Traits, scene_for, traits_for

DEFAULT_PROVIDER = "synthetic"
REGISTERED = ("synthetic", "directory", "comfyui")


def build_provider(name: str = DEFAULT_PROVIDER, **options: Any) -> GenerationProvider:
    """Construct a provider by name.

    ``directory`` needs ``root=``; ``comfyui`` needs ``base_url=`` and
    ``workflow_path=``. Missing options raise here rather than half-way through a
    batch, so a misconfigured run fails before it writes anything.
    """
    if name == "synthetic":
        return SyntheticProvider()
    if name == "directory":
        root = options.get("root")
        if root is None:
            raise ProviderError("The directory provider needs root=<path to images>")
        return DirectoryProvider(Path(root))
    if name == "comfyui":
        base_url = options.get("base_url")
        workflow = options.get("workflow_path")
        if not base_url or not workflow:
            raise ProviderError(
                "The comfyui provider needs base_url=<http://host:8188> "
                "and workflow_path=<api.json>"
            )
        from identitylock.providers.comfyui import ComfyUIProvider

        return ComfyUIProvider(str(base_url), Path(workflow))
    raise ProviderError(f"Unknown provider '{name}'. Available: {', '.join(REGISTERED)}")


__all__ = [
    "DEFAULT_PROVIDER",
    "REGISTERED",
    "DirectoryProvider",
    "GenerationProvider",
    "GenerationRequest",
    "ProviderError",
    "Scene",
    "SyntheticProvider",
    "Traits",
    "build_provider",
    "scene_for",
    "traits_for",
]
