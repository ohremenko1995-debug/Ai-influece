"""Image descriptors. One protocol, several backends, one honest default."""

from identitylock.embeddings.base import Descriptor, Embedder, Vector, cosine, l2_normalise
from identitylock.embeddings.classical import ClassicalEmbedder
from identitylock.embeddings.registry import DEFAULT_EMBEDDER, get_embedder, registered

__all__ = [
    "DEFAULT_EMBEDDER",
    "ClassicalEmbedder",
    "Descriptor",
    "Embedder",
    "Vector",
    "cosine",
    "get_embedder",
    "l2_normalise",
    "registered",
]
