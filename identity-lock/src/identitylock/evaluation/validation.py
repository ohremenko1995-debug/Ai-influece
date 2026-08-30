"""Rendering the labelled validation set the threshold is calibrated on.

Three seed ranges, deliberately disjoint:

* ``9000+`` — reference frames (the yardstick),
* ``7000+`` — validation frames (where the threshold comes from),
* the suite's own seeds — evaluation frames (what gets judged).

Overlapping any two of them would fit the gate on the data it later grades. The
separation is the reason a passing run means anything.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from identitylock.domain.models import PromptSpec
from identitylock.evaluation.suite import SuiteFile
from identitylock.providers.base import GenerationProvider, GenerationRequest

VALIDATION_SEED_BASE = 7_000
Progress = Callable[[str, int, int], None]


def render_validation(
    suite_file: SuiteFile,
    provider: GenerationProvider,
    *,
    recipe_id: str,
    output_root: Path,
    seeds: int = 3,
    progress: Progress | None = None,
) -> dict[str, list[Path]]:
    """Render ``seeds`` frames per prompt for every character in the cohort.

    Production conditions, not studio ones: the validation frames must look like
    what the harness will be asked to judge, or the threshold read off them will
    not transfer.
    """
    recipe = suite_file.recipe(recipe_id)
    rendered: dict[str, list[Path]] = {}

    for character_id in suite_file.cohort_ids():
        character = suite_file.character_object(character_id)
        directory = output_root / character_id
        directory.mkdir(parents=True, exist_ok=True)
        paths: list[Path] = []
        cells = [
            (prompt, VALIDATION_SEED_BASE + offset)
            for prompt in suite_file.prompts
            for offset in range(seeds)
        ]
        for index, (prompt_entry, seed) in enumerate(cells):
            if progress is not None:
                progress(character_id, index + 1, len(cells))
            request = GenerationRequest(
                character=character,
                prompt=PromptSpec(
                    id=prompt_entry.id, text=prompt_entry.text, tags=tuple(prompt_entry.tags)
                ),
                seed=seed,
                index=index,
                recipe=recipe,
                output_dir=directory,
            )
            paths.append(provider.generate(request).image_path)
        rendered[character_id] = paths

    return rendered
