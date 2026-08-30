"""Immutable domain objects.

Every model here is frozen and forbids unknown fields. A run is therefore a value
that can be hashed, serialised, diffed and replayed, which is the whole point of
an evaluation harness: two runs of the same suite must be comparable object for
object, not "roughly the same shape".
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Decision = Literal["accept", "reject"]
ComparisonOutcome = Literal["improvement", "regression", "inconclusive"]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


def content_hash(payload: object) -> str:
    """Stable content hash of any JSON-serialisable payload.

    Canonical form: sorted keys, no insignificant whitespace, UTF-8. The same
    logical value always hashes the same way regardless of construction order,
    which is what makes a recipe revision a *content* address rather than a label.
    """
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]


# --------------------------------------------------------------------------- #
# Generation inputs
# --------------------------------------------------------------------------- #

_RECIPE_SEALED_FIELDS = (
    "provider",
    "model",
    "sampler",
    "scheduler",
    "steps",
    "cfg",
    "width",
    "height",
    "loras",
    "prompt_prefix",
    "prompt_suffix",
    "negative_prompt",
    "extra",
)


class LoraRef(_Frozen):
    """A LoRA attached to a recipe, with the weight it is attached at."""

    name: str
    weight: float = Field(ge=0.0, le=2.0)


class Recipe(_Frozen):
    """A generation configuration.

    Recipes are never edited in place. `revision` is derived from the fields that
    change what comes out of the model, so any change to the recipe is a new
    revision and every candidate carries the revision it was produced under.
    """

    id: str
    name: str
    provider: str = "synthetic"
    model: str = "synthetic-v1"
    sampler: str = "euler"
    scheduler: str = "simple"
    steps: int = Field(default=8, ge=1, le=200)
    cfg: float = Field(default=1.0, ge=0.0, le=30.0)
    width: int = Field(default=768, ge=64, le=4096)
    height: int = Field(default=768, ge=64, le=4096)
    loras: tuple[LoraRef, ...] = ()
    prompt_prefix: str = ""
    prompt_suffix: str = ""
    negative_prompt: str = ""
    extra: dict[str, float | int | str | bool] = Field(default_factory=dict)
    revision: str = ""

    @model_validator(mode="after")
    def _seal_revision(self) -> Recipe:
        # Derived after defaults are applied, so an explicit `steps=8` and an
        # omitted `steps` seal to the same revision. A revision supplied by a
        # caller (or read back from an archived report) is always recomputed and
        # overwritten, so a report can never claim a revision its fields do not
        # produce. `object.__setattr__` is the documented way to assign a derived
        # field on a frozen pydantic model.
        dumped = self.model_dump(mode="json")
        sealed = {key: dumped[key] for key in _RECIPE_SEALED_FIELDS}
        object.__setattr__(self, "revision", content_hash(sealed))
        return self


class PromptSpec(_Frozen):
    """One prompt in a suite, addressable by id so runs can be paired."""

    id: str
    text: str
    tags: tuple[str, ...] = ()


class Character(_Frozen):
    """The identity under test.

    `disclosure` is not decoration: this tool exists for openly virtual personas,
    and the field travels with the character into every report so a reviewer can
    never look at a run without seeing what it was for.
    """

    id: str
    name: str
    disclosure: str = "Openly virtual character. Not a real person."
    reference_paths: tuple[Path, ...] = ()
    notes: str = ""


class Suite(_Frozen):
    """A reproducible unit of evaluation: who, under what prompts and seeds, how."""

    id: str
    character: Character
    prompts: tuple[PromptSpec, ...]
    seeds: tuple[int, ...]
    recipe: Recipe
    cohort_ids: tuple[str, ...] = ()
    description: str = ""

    @property
    def plan(self) -> tuple[tuple[PromptSpec, int], ...]:
        """The full (prompt, seed) grid, in the order both sides of an A/B execute.

        **Seed-major, not prompt-major.** The batch runs every prompt once, then
        every prompt again with the next seed. This is an experiment-design
        decision, not a cosmetic one: with a prompt-major plan the hardest prompt
        sits at the end of the batch, position in the batch is aliased with prompt
        difficulty, and the drift slope measures the order of the prompt list
        rather than anything about the pipeline. Interleaving spreads every prompt
        evenly across the index so a downward slope means the batch actually
        degraded.

        The order is fixed and deterministic, so both sides of a paired comparison
        walk the same cells in the same sequence.
        """
        return tuple((prompt, seed) for seed in self.seeds for prompt in self.prompts)


# --------------------------------------------------------------------------- #
# Generation outputs
# --------------------------------------------------------------------------- #


class Candidate(_Frozen):
    """One generated image plus the inputs that produced it."""

    id: str
    prompt_id: str
    prompt: str
    seed: int
    recipe_revision: str
    provider: str
    image_path: Path
    image_sha256: str
    latency_ms: float = 0.0

    @property
    def cell(self) -> tuple[str, int]:
        """The paired-design key: same prompt, same seed, different recipe."""
        return (self.prompt_id, self.seed)


# --------------------------------------------------------------------------- #
# Measurements
# --------------------------------------------------------------------------- #


class FrameStats(_Frozen):
    """Technical measurements of the frame itself, all in [0, 1] unless noted."""

    width: int
    height: int
    sharpness: float
    exposure: float
    contrast: float
    colorfulness: float
    clipping: float
    entropy: float


class CandidateMetrics(_Frozen):
    """Everything measured about one candidate.

    `identity_similarity` is cosine against the character's reference centroid.
    `identity_margin` is that similarity minus the best impostor centroid in the
    cohort — a verification-style margin, and the number that actually says
    "this is our character and not someone else's".
    """

    identity_similarity: float
    nearest_reference: float
    identity_margin: float | None = None
    impostor_best: float | None = None
    impostor_id: str | None = None
    technical_score: float = 0.0
    frame: FrameStats


class ScoredCandidate(_Frozen):
    """A candidate with its measurements and the gate decision."""

    candidate: Candidate
    metrics: CandidateMetrics
    decision: Decision
    rejections: tuple[str, ...] = ()
    selected: bool = False

    @property
    def id(self) -> str:
        return self.candidate.id


# --------------------------------------------------------------------------- #
# Run level
# --------------------------------------------------------------------------- #


class RunAggregates(_Frozen):
    """Run-level statistics. Percentiles are the honest summary; means flatter."""

    n_total: int
    n_accepted: int
    identity_mean: float
    identity_std: float
    identity_p05: float
    identity_min: float
    identity_max: float
    margin_mean: float | None
    technical_mean: float
    consistency_rate: float
    diversity: float
    drift_slope: float
    drift_r2: float
    drift_p_value: float
    identity_ci_low: float
    identity_ci_high: float


class GateOutcome(_Frozen):
    """One policy gate and how it landed. Reports never say "failed" without this."""

    name: str
    passed: bool
    observed: float | None
    threshold: float | None
    detail: str = ""


class RunVerdict(_Frozen):
    passed: bool
    gates: tuple[GateOutcome, ...]

    @property
    def failed_gates(self) -> tuple[str, ...]:
        return tuple(gate.name for gate in self.gates if not gate.passed)


class RunManifest(_Frozen):
    """What it would take to reproduce this run byte for byte."""

    tool_version: str
    report_schema_version: int
    created_at: datetime
    python_version: str
    platform: str
    provider: str
    embedder: str
    embedder_dim: int
    suite_id: str
    character_id: str
    recipe_revision: str
    policy_hash: str
    reference_hashes: tuple[str, ...] = ()


class RunResult(_Frozen):
    """The complete, self-describing result of evaluating one suite."""

    run_id: str
    label: str
    manifest: RunManifest
    suite: Suite
    candidates: tuple[ScoredCandidate, ...]
    aggregates: RunAggregates
    verdict: RunVerdict

    @property
    def accepted(self) -> tuple[ScoredCandidate, ...]:
        return tuple(item for item in self.candidates if item.decision == "accept")

    @property
    def selected(self) -> tuple[ScoredCandidate, ...]:
        return tuple(item for item in self.candidates if item.selected)

    def by_cell(self) -> dict[tuple[str, int], ScoredCandidate]:
        return {item.candidate.cell: item for item in self.candidates}


# --------------------------------------------------------------------------- #
# A/B comparison
# --------------------------------------------------------------------------- #


class PairedDelta(_Frozen):
    """One cell of the paired design: identical prompt and seed, two recipes."""

    prompt_id: str
    seed: int
    baseline: float
    challenger: float

    @property
    def delta(self) -> float:
        return self.challenger - self.baseline


class ComparisonVerdict(_Frozen):
    outcome: ComparisonOutcome
    gates: tuple[GateOutcome, ...]
    rationale: str


class Comparison(_Frozen):
    """A paired A/B between two runs of the same suite plan."""

    comparison_id: str
    metric: str
    baseline_run_id: str
    baseline_label: str
    challenger_run_id: str
    challenger_label: str
    pairs: tuple[PairedDelta, ...]
    win_rate: float
    mean_delta: float
    ci_low: float
    ci_high: float
    effect_size: float
    n_pairs: int
    verdict: ComparisonVerdict
