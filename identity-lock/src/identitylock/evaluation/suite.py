"""Loading a suite from disk.

A suite file is the whole experiment in one readable document: who is being
tested, against which prompts and seeds, under which recipes, and what counts as
passing. Keeping it declarative is what makes a run re-runnable by someone who
was not there when it was designed.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

from identitylock.domain.models import Character, LoraRef, PromptSpec, Recipe, Suite
from identitylock.domain.policy import ComparisonPolicy, Policy


class SuiteFileError(ValueError):
    """A suite file that cannot be trusted to mean what it says."""


class CharacterSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    disclosure: str = "Openly virtual character. Not a real person."
    references: Path
    notes: str = ""


class RecipeSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    provider: str = "synthetic"
    model: str = "synthetic-v1"
    sampler: str = "euler"
    scheduler: str = "simple"
    steps: int = 8
    cfg: float = 1.0
    width: int = 512
    height: int = 512
    loras: list[LoraRef] = Field(default_factory=list)
    prompt_prefix: str = ""
    prompt_suffix: str = ""
    negative_prompt: str = ""
    extra: dict[str, float | int | str | bool] = Field(default_factory=dict)

    def to_recipe(self, recipe_id: str) -> Recipe:
        return Recipe(
            id=recipe_id,
            name=self.name,
            provider=self.provider,
            model=self.model,
            sampler=self.sampler,
            scheduler=self.scheduler,
            steps=self.steps,
            cfg=self.cfg,
            width=self.width,
            height=self.height,
            loras=tuple(self.loras),
            prompt_prefix=self.prompt_prefix,
            prompt_suffix=self.prompt_suffix,
            negative_prompt=self.negative_prompt,
            extra=dict(self.extra),
        )


class PromptEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    text: str
    tags: list[str] = Field(default_factory=list)


class SuiteFile(BaseModel):
    """The parsed suite document, before it becomes domain objects."""

    model_config = ConfigDict(extra="forbid")

    id: str
    description: str = ""
    character: str
    cohort: list[str] = Field(default_factory=list)
    characters: dict[str, CharacterSpec]
    prompts: list[PromptEntry]
    seeds: list[int]
    recipes: dict[str, RecipeSpec]
    reference_recipe: str | None = None
    reference_count: int = Field(default=6, ge=1, le=64)
    policy: Policy = Field(default_factory=Policy)
    comparison_policy: ComparisonPolicy = Field(default_factory=ComparisonPolicy)
    select_k: int = Field(default=6, ge=0, le=256)
    select_lambda: float = Field(default=0.7, ge=0.0, le=1.0)

    base_dir: Path = Field(default=Path(), exclude=True)

    def character_object(self, character_id: str) -> Character:
        try:
            spec = self.characters[character_id]
        except KeyError:
            known = ", ".join(sorted(self.characters))
            raise SuiteFileError(f"Unknown character '{character_id}'. Declared: {known}") from None
        return Character(
            id=character_id,
            name=spec.name,
            disclosure=spec.disclosure,
            reference_paths=(),
            notes=spec.notes,
        )

    def reference_dir(self, character_id: str) -> Path:
        spec = self.characters[character_id]
        path = spec.references
        return path if path.is_absolute() else (self.base_dir / path)

    def cohort_ids(self) -> tuple[str, ...]:
        declared = self.cohort or list(self.characters)
        if self.character not in declared:
            declared = [self.character, *declared]
        return tuple(dict.fromkeys(declared))

    def recipe(self, recipe_id: str) -> Recipe:
        try:
            return self.recipes[recipe_id].to_recipe(recipe_id)
        except KeyError:
            known = ", ".join(sorted(self.recipes))
            raise SuiteFileError(f"Unknown recipe '{recipe_id}'. Declared: {known}") from None

    def to_suite(self, recipe_id: str) -> Suite:
        return Suite(
            id=self.id,
            character=self.character_object(self.character),
            prompts=tuple(
                PromptSpec(id=entry.id, text=entry.text, tags=tuple(entry.tags))
                for entry in self.prompts
            ),
            seeds=tuple(self.seeds),
            recipe=self.recipe(recipe_id),
            cohort_ids=self.cohort_ids(),
            description=self.description,
        )


def load_suite_file(path: Path) -> SuiteFile:
    """Parse and validate a suite document.

    Every consistency check that can be made without touching the filesystem is
    made here, so a typo in a character id fails in a hundred milliseconds rather
    than after a batch of renders.
    """
    path = Path(path)
    try:
        raw: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise SuiteFileError(f"Suite file not found: {path}") from None
    except yaml.YAMLError as error:
        raise SuiteFileError(f"{path} is not valid YAML: {error}") from None

    if not isinstance(raw, dict):
        raise SuiteFileError(f"{path} must contain a mapping at the top level")

    suite_file = SuiteFile.model_validate({**raw, "base_dir": path.parent})

    if suite_file.character not in suite_file.characters:
        known = ", ".join(sorted(suite_file.characters))
        raise SuiteFileError(
            f"character '{suite_file.character}' is not declared under 'characters' ({known})"
        )
    for member in suite_file.cohort:
        if member not in suite_file.characters:
            raise SuiteFileError(f"cohort member '{member}' is not declared under 'characters'")
    if not suite_file.prompts:
        raise SuiteFileError("a suite needs at least one prompt")
    if not suite_file.seeds:
        raise SuiteFileError("a suite needs at least one seed")
    if not suite_file.recipes:
        raise SuiteFileError("a suite needs at least one recipe")
    if suite_file.reference_recipe and suite_file.reference_recipe not in suite_file.recipes:
        raise SuiteFileError(
            f"reference_recipe '{suite_file.reference_recipe}' is not declared under 'recipes'"
        )

    duplicate_prompts = _duplicates([entry.id for entry in suite_file.prompts])
    if duplicate_prompts:
        raise SuiteFileError(f"duplicate prompt ids: {', '.join(duplicate_prompts)}")
    duplicate_seeds = _duplicates([str(seed) for seed in suite_file.seeds])
    if duplicate_seeds:
        raise SuiteFileError(f"duplicate seeds: {', '.join(duplicate_seeds)}")

    return suite_file


def _duplicates(values: list[str]) -> list[str]:
    seen: set[str] = set()
    repeated: list[str] = []
    for value in values:
        if value in seen and value not in repeated:
            repeated.append(value)
        seen.add(value)
    return repeated
