"""What a generation backend has to look like.

The rule the whole architecture rests on: **the evaluation layer never talks to a
model.** It asks a provider for a candidate and gets back a file on disk plus the
inputs that produced it. Swapping a procedural renderer for a remote ComfyUI box
therefore changes one line of configuration and nothing else — which is what
makes the metrics comparable across backends in the first place.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from identitylock.domain.models import Candidate, Character, PromptSpec, Recipe, _Frozen


class GenerationRequest(_Frozen):
    """One cell of a suite plan, plus where to put the result."""

    character: Character
    prompt: PromptSpec
    seed: int
    index: int
    recipe: Recipe
    output_dir: Path

    @property
    def candidate_id(self) -> str:
        return f"{self.character.id}.{self.prompt.id}.{self.seed:010d}"


class ProviderError(RuntimeError):
    """A provider failed to produce an image. Never swallowed, never faked."""


@runtime_checkable
class GenerationProvider(Protocol):
    @property
    def name(self) -> str:
        """Identifier recorded on every candidate and in the run manifest."""

    def generate(self, request: GenerationRequest) -> Candidate:
        """Produce exactly one image and describe how it was produced."""


__all__ = [
    "Candidate",
    "Character",
    "GenerationProvider",
    "GenerationRequest",
    "PromptSpec",
    "ProviderError",
    "Recipe",
]
