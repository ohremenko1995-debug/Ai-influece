"""Backend selection by name, with an error that says how to fix itself."""

from __future__ import annotations

from collections.abc import Callable

from identitylock.embeddings.base import Embedder
from identitylock.embeddings.classical import ClassicalEmbedder

_FACTORIES: dict[str, Callable[[], Embedder]] = {}


def _register(name: str, factory: Callable[[], Embedder]) -> None:
    _FACTORIES[name] = factory


def _clip() -> Embedder:
    from identitylock.embeddings.learned import ClipEmbedder

    return ClipEmbedder()


def _arcface() -> Embedder:
    from identitylock.embeddings.learned import ArcFaceEmbedder

    return ArcFaceEmbedder()


_register("classical", ClassicalEmbedder)
_register("clip", _clip)
_register("arcface", _arcface)

DEFAULT_EMBEDDER = "classical"


def registered() -> tuple[str, ...]:
    """Every backend name the CLI accepts, installed or not."""
    return tuple(sorted(_FACTORIES))


def get_embedder(name: str = DEFAULT_EMBEDDER) -> Embedder:
    """Build a backend by name.

    A learned backend raises ``MissingBackendError`` with an install line if its
    dependency is absent. It is never silently swapped for the classical one:
    a run labelled ``arcface`` in the manifest must have been produced by arcface.
    """
    try:
        factory = _FACTORIES[name]
    except KeyError:
        known = ", ".join(registered())
        raise ValueError(f"Unknown embedder '{name}'. Available: {known}") from None
    return factory()
