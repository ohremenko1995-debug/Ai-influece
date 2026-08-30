"""Rendering the synthetic reference sets the demo needs.

Reference images are the yardstick, so they are never committed as binaries: they
are rendered from the suite file, deterministically, on first use. A clean
checkout and a fresh render produce byte-identical references, which is the only
way the shipped thresholds can mean anything on someone else's machine.

Reference frames are rendered with identity jitter forced to zero and under the
neutral studio scene — a golden set is by definition the character as intended,
shot under controlled conditions, not a sample of what the pipeline happens to
produce today.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from identitylock.domain.models import PromptSpec, Recipe
from identitylock.evaluation.suite import SuiteFile
from identitylock.providers.base import GenerationProvider, GenerationRequest

REFERENCE_SEED_BASE = 9_000
Progress = Callable[[str, int, int], None]


def reference_recipe(suite_file: SuiteFile) -> Recipe:
    """The recipe references are rendered under: no jitter, no drift, no blur."""
    recipe_id = suite_file.reference_recipe or next(iter(suite_file.recipes))
    recipe = suite_file.recipe(recipe_id)
    clean: dict[str, float | int | str | bool] = {
        key: value
        for key, value in recipe.extra.items()
        if key not in {"identity_jitter", "drift_per_frame", "blur", "exposure_bias"}
    }
    clean["neutral_scene"] = True
    return recipe.model_copy(update={"extra": clean, "id": f"{recipe_id}:reference"})


def render_references(
    suite_file: SuiteFile,
    provider: GenerationProvider,
    *,
    count: int | None = None,
    force: bool = False,
    progress: Progress | None = None,
) -> dict[str, list[Path]]:
    """Render ``count`` reference frames for every character in the cohort.

    Existing files are left alone unless ``force`` is set: re-rendering over a
    curated reference set that someone replaced by hand would silently destroy
    the very thing the run is measured against.
    """
    total = count or suite_file.reference_count
    recipe = reference_recipe(suite_file)
    rendered: dict[str, list[Path]] = {}

    for character_id in suite_file.cohort_ids():
        character = suite_file.character_object(character_id)
        directory = suite_file.reference_dir(character_id)
        directory.mkdir(parents=True, exist_ok=True)
        paths: list[Path] = []

        for index in range(total):
            prompt = PromptSpec(id=f"ref{index:02d}", text="neutral reference frame")
            request = GenerationRequest(
                character=character,
                prompt=prompt,
                seed=REFERENCE_SEED_BASE + index,
                index=index,
                recipe=recipe,
                output_dir=directory,
            )
            target = directory / f"{request.candidate_id}.png"
            if target.exists() and not force:
                paths.append(target)
                continue
            if progress is not None:
                progress(character_id, index + 1, total)
            paths.append(provider.generate(request).image_path)

        rendered[character_id] = paths

    return rendered
