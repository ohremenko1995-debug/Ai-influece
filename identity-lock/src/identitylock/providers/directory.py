"""Score images that were generated somewhere else.

This is the provider that matters in practice. Real frames come off a GPU box, a
hosted API or an artist's drive; the harness should measure them without pretending
it produced them. Point it at a folder whose files are named
``<character>.<prompt>.<seed>.png`` — the same id the harness assigns — and every
metric, gate and report works unchanged.
"""

from __future__ import annotations

import time
from pathlib import Path

from identitylock.domain.models import Candidate
from identitylock.imaging.loader import sha256_file
from identitylock.providers.base import GenerationRequest, ProviderError

_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp")


class DirectoryProvider:
    """Resolve each requested cell to an existing file. Generates nothing."""

    name = "directory"

    def __init__(self, root: Path) -> None:
        self._root = Path(root)
        if not self._root.is_dir():
            raise ProviderError(f"Image directory does not exist: {self._root}")

    def _resolve(self, request: GenerationRequest) -> Path:
        for suffix in _SUFFIXES:
            candidate = self._root / f"{request.candidate_id}{suffix}"
            if candidate.is_file():
                return candidate
        raise ProviderError(
            f"No image for cell '{request.candidate_id}' under {self._root}. "
            f"Expected one of: {', '.join(request.candidate_id + suffix for suffix in _SUFFIXES)}"
        )

    def generate(self, request: GenerationRequest) -> Candidate:
        started = time.perf_counter()
        path = self._resolve(request)
        return Candidate(
            id=request.candidate_id,
            prompt_id=request.prompt.id,
            prompt=request.prompt.text,
            seed=request.seed,
            recipe_revision=request.recipe.revision,
            provider=self.name,
            image_path=path,
            image_sha256=sha256_file(path),
            latency_ms=round((time.perf_counter() - started) * 1000.0, 3),
        )
