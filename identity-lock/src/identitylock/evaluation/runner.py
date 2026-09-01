"""The orchestrator: suite in, scored run out.

The order of operations is the design. References are described and the identity
space is fitted **before** a single candidate is generated, so the yardstick
cannot be influenced by what is being measured. Candidates are then generated in
plan order and scored one at a time, which is what makes the drift slope mean
"across this batch, in this order" rather than "across an arbitrary shuffle".
"""

from __future__ import annotations

import platform
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from identitylock import REPORT_SCHEMA_VERSION, __version__
from identitylock.domain.models import (
    Candidate,
    CandidateMetrics,
    RunAggregates,
    RunManifest,
    RunResult,
    ScoredCandidate,
)
from identitylock.domain.policy import Policy, evaluate_candidate, evaluate_run
from identitylock.embeddings.base import Embedder, ReportsMisses, Vector
from identitylock.evaluation.suite import SuiteFile
from identitylock.imaging.loader import load_image, sha256_file
from identitylock.imaging.stats import frame_stats, technical_score
from identitylock.metrics.aggregate import bootstrap_ci, mean, percentile, std, stratified_drift
from identitylock.metrics.diversity import mean_pairwise_distance
from identitylock.metrics.identity import (
    ReferenceProfile,
    build_profile,
    impostor_margin,
    nearest_reference,
    similarity,
)
from identitylock.metrics.space import IdentitySpace
from identitylock.providers.base import GenerationProvider, GenerationRequest, ProviderError
from identitylock.selection.selector import select_takes

IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp")
Progress = Callable[[int, int, str], None]


class EvaluationError(RuntimeError):
    """The run cannot proceed, and says why in a sentence a human can act on."""


@dataclass(frozen=True, slots=True)
class Cohort:
    """The fitted yardstick: one identity space, one profile per character."""

    space: IdentitySpace
    profiles: dict[str, ReferenceProfile]

    def profile(self, character_id: str) -> ReferenceProfile:
        try:
            return self.profiles[character_id]
        except KeyError:
            raise EvaluationError(f"No reference profile for character '{character_id}'") from None

    @property
    def impostors(self) -> list[ReferenceProfile]:
        return list(self.profiles.values())


def reference_paths(directory: Path) -> list[Path]:
    """Every image in a reference directory, in a stable order."""
    if not directory.is_dir():
        return []
    return sorted(
        path
        for path in directory.iterdir()
        if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
    )


class Evaluator:
    """Runs suites. Holds no state between runs beyond its configuration."""

    def __init__(
        self,
        *,
        provider: GenerationProvider,
        embedder: Embedder,
        policy: Policy,
        select_k: int = 6,
        select_lambda: float = 0.7,
        centre_space: bool = True,
        bootstrap_seed: int = 20240101,
    ) -> None:
        self._provider = provider
        self._embedder = embedder
        self._policy = policy
        self._select_k = select_k
        self._select_lambda = select_lambda
        self._centre_space = centre_space
        self._bootstrap_seed = bootstrap_seed

    # ------------------------------------------------------------------ #
    # Cohort
    # ------------------------------------------------------------------ #

    def build_cohort(self, suite_file: SuiteFile, character_ids: Sequence[str]) -> Cohort:
        """Describe every reference image in the cohort and fit the identity space."""
        raw: dict[str, list[Vector]] = {}
        hashes: dict[str, list[str]] = {}

        for character_id in character_ids:
            directory = suite_file.reference_dir(character_id)
            paths = reference_paths(directory)
            if not paths:
                raise EvaluationError(
                    f"Character '{character_id}' has no reference images in {directory}. "
                    "Render the synthetic reference sets with `identitylock bootstrap`, "
                    "or point 'references:' at a folder of curated frames."
                )
            raw[character_id] = [
                self._embedder.describe(load_image(path)).identity for path in paths
            ]
            hashes[character_id] = [sha256_file(path) for path in paths]

        pooled = [vector for vectors in raw.values() for vector in vectors]
        space = (
            IdentitySpace.fit(pooled) if self._centre_space else IdentitySpace.unit(len(pooled[0]))
        )
        profiles = {
            character_id: build_profile(
                character_id, space.project_all(vectors), hashes[character_id]
            )
            for character_id, vectors in raw.items()
        }
        return Cohort(space=space, profiles=profiles)

    # ------------------------------------------------------------------ #
    # Run
    # ------------------------------------------------------------------ #

    def run(
        self,
        suite_file: SuiteFile,
        recipe_id: str,
        *,
        run_dir: Path,
        cohort: Cohort | None = None,
        run_id: str | None = None,
        label: str | None = None,
        progress: Progress | None = None,
    ) -> RunResult:
        """Generate and score one suite under one recipe."""
        suite = suite_file.to_suite(recipe_id)
        cohort = cohort or self.build_cohort(suite_file, suite.cohort_ids)
        own = cohort.profile(suite.character.id)

        image_dir = run_dir / "images"
        image_dir.mkdir(parents=True, exist_ok=True)

        plan = suite.plan
        scored: list[ScoredCandidate] = []
        content_vectors: list[Vector] = []

        for index, (prompt, seed) in enumerate(plan):
            request = GenerationRequest(
                character=suite.character,
                prompt=prompt,
                seed=seed,
                index=index,
                recipe=suite.recipe,
                output_dir=image_dir,
            )
            if progress is not None:
                progress(index + 1, len(plan), request.candidate_id)

            try:
                candidate = self._provider.generate(request)
            except ProviderError as error:
                raise EvaluationError(
                    f"Provider '{getattr(self._provider, 'name', '?')}' failed on "
                    f"cell {request.candidate_id}: {error}"
                ) from error

            # One describe() per frame. The previous shape called it twice — once
            # for identity inside _score and once for content here — which doubled
            # the most expensive step in the loop, and with a learned backend meant
            # two forward passes per frame.
            item, content = self._score(candidate, cohort, own)
            scored.append(item)
            content_vectors.append(content)

        scored = self._apply_selection(scored, content_vectors)
        aggregates = self._aggregate(scored, content_vectors)
        verdict = evaluate_run(aggregates, self._policy)

        stamp = datetime.now(UTC)
        return RunResult(
            run_id=run_id or f"{suite.id}.{recipe_id}.{stamp.strftime('%Y%m%dT%H%M%SZ')}",
            label=label or f"{suite.recipe.name} ({recipe_id})",
            manifest=RunManifest(
                tool_version=__version__,
                report_schema_version=REPORT_SCHEMA_VERSION,
                created_at=stamp,
                python_version=sys.version.split()[0],
                platform=platform.platform(),
                provider=str(getattr(self._provider, "name", "unknown")),
                embedder=str(self._embedder.name),
                embedder_dim=int(self._embedder.identity_dim),
                suite_id=suite.id,
                character_id=suite.character.id,
                recipe_revision=suite.recipe.revision,
                policy_hash=self._policy.fingerprint(),
                policy=self._policy,
                identity_space=cohort.space.fingerprint(),
                embedder_misses=(
                    self._embedder.misses if isinstance(self._embedder, ReportsMisses) else 0
                ),
                reference_hashes=own.hashes,
            ),
            suite=suite,
            candidates=tuple(scored),
            aggregates=aggregates,
            verdict=verdict,
        )

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #

    def _score(
        self, candidate: Candidate, cohort: Cohort, own: ReferenceProfile
    ) -> tuple[ScoredCandidate, Vector]:
        """Score one candidate, returning it with its content vector.

        Both vectors come from a single ``describe()`` call: identity is scored here
        and content is handed back for diversity and the shortlist.
        """
        image = load_image(candidate.image_path)
        descriptor = self._embedder.describe(image)
        projected = cohort.space.project(descriptor.identity)

        margin, impostor_best, impostor_id = impostor_margin(projected, own, cohort.impostors)
        stats = frame_stats(image)
        metrics = CandidateMetrics(
            identity_similarity=round(similarity(projected, own), 6),
            nearest_reference=round(nearest_reference(projected, own), 6),
            identity_margin=None if margin is None else round(margin, 6),
            impostor_best=None if impostor_best is None else round(impostor_best, 6),
            impostor_id=impostor_id,
            technical_score=technical_score(stats),
            frame=stats,
        )
        decision, rejections = evaluate_candidate(metrics, self._policy)
        return (
            ScoredCandidate(
                candidate=candidate, metrics=metrics, decision=decision, rejections=rejections
            ),
            descriptor.content,
        )

    def _apply_selection(
        self, scored: Sequence[ScoredCandidate], content: Sequence[Vector]
    ) -> list[ScoredCandidate]:
        """Shortlist accepted takes with MMR and mark them on the results."""
        relevance = [
            0.7 * item.metrics.identity_similarity + 0.3 * item.metrics.technical_score
            for item in scored
        ]
        eligible = [item.decision == "accept" for item in scored]
        selection = select_takes(
            relevance, content, k=self._select_k, lambda_=self._select_lambda, eligible=eligible
        )
        chosen = set(selection.indices)
        return [
            item.model_copy(update={"selected": index in chosen})
            for index, item in enumerate(scored)
        ]

    def _aggregate(
        self, scored: Sequence[ScoredCandidate], content: Sequence[Vector]
    ) -> RunAggregates:
        identity = [item.metrics.identity_similarity for item in scored]
        margins = [
            item.metrics.identity_margin
            for item in scored
            if item.metrics.identity_margin is not None
        ]
        accepted_content = [
            vector
            for vector, item in zip(content, scored, strict=True)
            if item.decision == "accept"
        ]
        slope, r_squared, drift_p = stratified_drift(
            identity,
            [item.candidate.prompt_id for item in scored],
            seed=self._bootstrap_seed,
        )
        low, high = bootstrap_ci(identity, seed=self._bootstrap_seed)
        accepted = sum(1 for item in scored if item.decision == "accept")

        return RunAggregates(
            n_total=len(scored),
            n_accepted=accepted,
            identity_mean=round(mean(identity), 6),
            identity_std=round(std(identity), 6),
            identity_p05=round(percentile(identity, 5.0), 6),
            identity_min=round(min(identity), 6) if identity else 0.0,
            identity_max=round(max(identity), 6) if identity else 0.0,
            margin_mean=round(mean(margins), 6) if margins else None,
            technical_mean=round(mean([item.metrics.technical_score for item in scored]), 6),
            consistency_rate=round(accepted / len(scored), 6) if scored else 0.0,
            diversity=round(mean_pairwise_distance(accepted_content), 6),
            drift_slope=round(slope, 6),
            drift_r2=round(r_squared, 6),
            drift_p_value=round(drift_p, 6),
            identity_ci_low=round(low, 6),
            identity_ci_high=round(high, 6),
        )
