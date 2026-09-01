"""Suite loading, the end-to-end run, comparison guards and the store."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from identitylock.domain.models import RunResult
from identitylock.evaluation import (
    ComparisonError,
    EvaluationError,
    Evaluator,
    SuiteFile,
    SuiteFileError,
    compare,
    list_runs,
    load_run,
    load_suite_file,
    render_references,
    save_comparison,
    save_run,
)
from identitylock.evaluation.bootstrap import reference_recipe
from identitylock.evaluation.store import StoreError, list_comparisons, load_comparison
from identitylock.evaluation.validation import render_validation
from identitylock.providers import build_provider
from identitylock.providers.base import GenerationProvider
from tests.conftest import TINY_SUITE


def _write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "suite.yaml"
    path.write_text(body, encoding="utf-8")
    return path


class TestSuiteFile:
    def test_loads_the_tiny_suite(self, suite_file: SuiteFile) -> None:
        assert suite_file.id == "tiny"
        assert suite_file.cohort_ids() == ("alpha", "beta")
        assert len(suite_file.to_suite("locked").plan) == 4

    def test_reference_paths_resolve_next_to_the_suite(
        self, suite_file: SuiteFile, suite_path: Path
    ) -> None:
        assert suite_file.reference_dir("alpha") == suite_path.parent / "references/alpha"

    def test_the_subject_is_always_in_the_cohort(self, tmp_path: Path) -> None:
        body = TINY_SUITE.replace("cohort: [alpha, beta]", "cohort: [beta]")
        assert load_suite_file(_write(tmp_path, body)).cohort_ids()[0] == "alpha"

    def test_missing_file(self, tmp_path: Path) -> None:
        with pytest.raises(SuiteFileError, match="not found"):
            load_suite_file(tmp_path / "absent.yaml")

    def test_invalid_yaml(self, tmp_path: Path) -> None:
        with pytest.raises(SuiteFileError, match="not valid YAML"):
            load_suite_file(_write(tmp_path, "id: [unclosed\n"))

    def test_a_scalar_document(self, tmp_path: Path) -> None:
        with pytest.raises(SuiteFileError, match="mapping"):
            load_suite_file(_write(tmp_path, "just a string\n"))

    def test_unknown_subject(self, tmp_path: Path) -> None:
        with pytest.raises(SuiteFileError, match="not declared"):
            load_suite_file(
                _write(tmp_path, TINY_SUITE.replace("character: alpha", "character: ghost"))
            )

    def test_unknown_cohort_member(self, tmp_path: Path) -> None:
        with pytest.raises(SuiteFileError, match="cohort member"):
            load_suite_file(
                _write(
                    tmp_path, TINY_SUITE.replace("cohort: [alpha, beta]", "cohort: [alpha, ghost]")
                )
            )

    def test_duplicate_prompt_ids(self, tmp_path: Path) -> None:
        body = TINY_SUITE.replace(
            "  - id: street\n    text: street portrait", "  - id: studio\n    text: duplicate"
        )
        with pytest.raises(SuiteFileError, match="duplicate prompt ids"):
            load_suite_file(_write(tmp_path, body))

    def test_duplicate_seeds(self, tmp_path: Path) -> None:
        with pytest.raises(SuiteFileError, match="duplicate seeds"):
            load_suite_file(
                _write(tmp_path, TINY_SUITE.replace("seeds: [11, 22]", "seeds: [11, 11]"))
            )

    def test_no_seeds(self, tmp_path: Path) -> None:
        with pytest.raises(SuiteFileError, match="at least one seed"):
            load_suite_file(_write(tmp_path, TINY_SUITE.replace("seeds: [11, 22]", "seeds: []")))

    def test_unknown_reference_recipe(self, tmp_path: Path) -> None:
        with pytest.raises(SuiteFileError, match="reference_recipe"):
            load_suite_file(
                _write(
                    tmp_path,
                    TINY_SUITE.replace("reference_recipe: locked", "reference_recipe: ghost"),
                )
            )

    def test_unknown_recipe_lists_the_known_ones(self, suite_file: SuiteFile) -> None:
        with pytest.raises(SuiteFileError, match="locked, loose"):
            suite_file.recipe("ghost")

    def test_an_unexpected_key_is_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError):
            load_suite_file(_write(tmp_path, TINY_SUITE + "\nmystery: 1\n"))


class TestReferences:
    def test_renders_the_whole_cohort(
        self, suite_file: SuiteFile, provider: GenerationProvider
    ) -> None:
        rendered = render_references(suite_file, provider)
        assert set(rendered) == {"alpha", "beta"}
        assert all(len(paths) == 4 for paths in rendered.values())

    def test_does_not_overwrite_by_default(
        self, suite_file: SuiteFile, provider: GenerationProvider
    ) -> None:
        """Someone may have replaced the synthetic set with curated frames."""
        first = render_references(suite_file, provider)["alpha"][0]
        first.write_bytes(first.read_bytes() + b"\x00")
        marked = first.read_bytes()
        render_references(suite_file, provider)
        assert first.read_bytes() == marked

    def test_force_re_renders(self, suite_file: SuiteFile, provider: GenerationProvider) -> None:
        first = render_references(suite_file, provider)["alpha"][0]
        original = first.read_bytes()
        first.write_bytes(b"\x89PNG\r\n\x1a\n")
        render_references(suite_file, provider, force=True)
        assert first.read_bytes() == original

    def test_the_reference_recipe_drops_the_failure_knobs(self, suite_file: SuiteFile) -> None:
        recipe = reference_recipe(suite_file)
        assert "identity_jitter" not in recipe.extra
        assert recipe.extra["neutral_scene"] is True

    def test_validation_uses_disjoint_seeds(
        self, suite_file: SuiteFile, provider: GenerationProvider, tmp_path: Path
    ) -> None:
        rendered = render_validation(
            suite_file, provider, recipe_id="locked", output_root=tmp_path / "val", seeds=2
        )
        seeds = {int(path.stem.split(".")[-1]) for path in rendered["alpha"]}
        assert seeds.isdisjoint(set(suite_file.seeds))
        assert all(seed >= 7000 for seed in seeds)


class TestEvaluator:
    def test_refuses_to_run_without_references(
        self, suite_file: SuiteFile, evaluator: Evaluator
    ) -> None:
        with pytest.raises(EvaluationError, match="identitylock bootstrap"):
            evaluator.build_cohort(suite_file, suite_file.cohort_ids())

    def test_scores_every_cell(
        self, bootstrapped: SuiteFile, evaluator: Evaluator, tmp_path: Path
    ) -> None:
        result = evaluator.run(bootstrapped, "locked", run_dir=tmp_path / "run", run_id="r1")
        assert len(result.candidates) == 4
        assert result.aggregates.n_total == 4

    def test_records_a_reproducible_manifest(
        self, bootstrapped: SuiteFile, evaluator: Evaluator, tmp_path: Path
    ) -> None:
        result = evaluator.run(bootstrapped, "locked", run_dir=tmp_path / "run", run_id="r1")
        manifest = result.manifest
        assert manifest.embedder == "classical-v1"
        assert manifest.recipe_revision == bootstrapped.recipe("locked").revision
        assert len(manifest.reference_hashes) == 4
        assert manifest.policy_hash == bootstrapped.policy.fingerprint()

    def test_is_reproducible(
        self, bootstrapped: SuiteFile, evaluator: Evaluator, tmp_path: Path
    ) -> None:
        first = evaluator.run(bootstrapped, "locked", run_dir=tmp_path / "a", run_id="r1")
        second = evaluator.run(bootstrapped, "locked", run_dir=tmp_path / "b", run_id="r1")
        assert first.aggregates == second.aggregates

    def test_shortlists_only_accepted_takes(
        self, bootstrapped: SuiteFile, evaluator: Evaluator, tmp_path: Path
    ) -> None:
        result = evaluator.run(bootstrapped, "locked", run_dir=tmp_path / "run", run_id="r1")
        assert all(item.decision == "accept" for item in result.selected)
        assert len(result.selected) <= bootstrapped.select_k

    def test_the_subject_beats_the_impostor(
        self, bootstrapped: SuiteFile, evaluator: Evaluator, tmp_path: Path
    ) -> None:
        result = evaluator.run(bootstrapped, "locked", run_dir=tmp_path / "run", run_id="r1")
        margins = [item.metrics.identity_margin for item in result.candidates]
        assert all(margin is not None and margin > 0 for margin in margins)

    def test_loose_recipes_score_worse_than_locked_ones(
        self, bootstrapped: SuiteFile, evaluator: Evaluator, tmp_path: Path
    ) -> None:
        locked = evaluator.run(bootstrapped, "locked", run_dir=tmp_path / "a", run_id="a")
        loose = evaluator.run(bootstrapped, "loose", run_dir=tmp_path / "b", run_id="b")
        assert locked.aggregates.identity_mean > loose.aggregates.identity_mean
        assert locked.aggregates.technical_mean > loose.aggregates.technical_mean

    def test_reports_progress(
        self, bootstrapped: SuiteFile, evaluator: Evaluator, tmp_path: Path
    ) -> None:
        seen: list[tuple[int, int]] = []
        evaluator.run(
            bootstrapped,
            "locked",
            run_dir=tmp_path / "run",
            run_id="r1",
            progress=lambda done, total, _label: seen.append((done, total)),
        )
        assert seen == [(1, 4), (2, 4), (3, 4), (4, 4)]


class TestComparison:
    def _runs(
        self, suite_file: SuiteFile, evaluator: Evaluator, tmp_path: Path
    ) -> tuple[RunResult, RunResult]:
        locked = evaluator.run(suite_file, "locked", run_dir=tmp_path / "a", run_id="a")
        loose = evaluator.run(suite_file, "loose", run_dir=tmp_path / "b", run_id="b")
        return loose, locked

    def test_finds_the_better_recipe(
        self, bootstrapped: SuiteFile, evaluator: Evaluator, tmp_path: Path
    ) -> None:
        baseline, challenger = self._runs(bootstrapped, evaluator, tmp_path)
        comparison = compare(baseline, challenger)
        assert comparison.n_pairs == 4
        assert comparison.mean_delta > 0

    def test_pairs_identical_cells(
        self, bootstrapped: SuiteFile, evaluator: Evaluator, tmp_path: Path
    ) -> None:
        baseline, challenger = self._runs(bootstrapped, evaluator, tmp_path)
        comparison = compare(baseline, challenger)
        cells = {(pair.prompt_id, pair.seed) for pair in comparison.pairs}
        assert cells == set(baseline.by_cell())

    def test_refuses_to_compare_a_run_with_itself(
        self, bootstrapped: SuiteFile, evaluator: Evaluator, tmp_path: Path
    ) -> None:
        locked = evaluator.run(bootstrapped, "locked", run_dir=tmp_path / "a", run_id="a")
        with pytest.raises(ComparisonError, match="same recipe revision"):
            compare(locked, locked)

    def test_refuses_an_unknown_metric(
        self, bootstrapped: SuiteFile, evaluator: Evaluator, tmp_path: Path
    ) -> None:
        baseline, challenger = self._runs(bootstrapped, evaluator, tmp_path)
        with pytest.raises(ComparisonError, match="Unknown metric"):
            compare(baseline, challenger, metric="vibes")

    def test_refuses_different_reference_sets(
        self, bootstrapped: SuiteFile, evaluator: Evaluator, tmp_path: Path
    ) -> None:
        """Identity numbers measured against different yardsticks are not comparable."""
        baseline, challenger = self._runs(bootstrapped, evaluator, tmp_path)
        forged = challenger.model_copy(
            update={"manifest": challenger.manifest.model_copy(update={"reference_hashes": ("x",)})}
        )
        with pytest.raises(ComparisonError, match="different reference images"):
            compare(baseline, forged)

    def test_refuses_different_embedders(
        self, bootstrapped: SuiteFile, evaluator: Evaluator, tmp_path: Path
    ) -> None:
        baseline, challenger = self._runs(bootstrapped, evaluator, tmp_path)
        forged = challenger.model_copy(
            update={
                "manifest": challenger.manifest.model_copy(update={"embedder": "clip:whatever"})
            }
        )
        with pytest.raises(ComparisonError, match="not on the same scale"):
            compare(baseline, forged)

    def test_refuses_mismatched_plans(
        self, bootstrapped: SuiteFile, evaluator: Evaluator, tmp_path: Path
    ) -> None:
        baseline, challenger = self._runs(bootstrapped, evaluator, tmp_path)
        trimmed = challenger.model_copy(update={"candidates": challenger.candidates[:2]})
        with pytest.raises(ComparisonError, match="not be paired"):
            compare(baseline, trimmed)


class TestStore:
    def test_round_trips_a_run(
        self, bootstrapped: SuiteFile, evaluator: Evaluator, tmp_path: Path
    ) -> None:
        runs = tmp_path / "runs"
        result = evaluator.run(bootstrapped, "locked", run_dir=runs / "r1", run_id="r1")
        save_run(result, runs)
        assert load_run(runs / "r1") == result

    def test_loads_from_the_json_directly(
        self, bootstrapped: SuiteFile, evaluator: Evaluator, tmp_path: Path
    ) -> None:
        runs = tmp_path / "runs"
        result = evaluator.run(bootstrapped, "locked", run_dir=runs / "r1", run_id="r1")
        path = save_run(result, runs)
        assert load_run(path).run_id == "r1"

    def test_lists_runs_newest_first(
        self, bootstrapped: SuiteFile, evaluator: Evaluator, tmp_path: Path
    ) -> None:
        runs = tmp_path / "runs"
        for name, recipe in (("a", "locked"), ("b", "loose")):
            save_run(evaluator.run(bootstrapped, recipe, run_dir=runs / name, run_id=name), runs)
        listed = list_runs(runs)
        assert len(listed) == 2
        assert listed[0].manifest.created_at >= listed[1].manifest.created_at

    def test_skips_directories_that_are_not_runs(self, tmp_path: Path) -> None:
        (tmp_path / "runs" / "junk").mkdir(parents=True)
        assert list_runs(tmp_path / "runs") == []

    def test_a_missing_root_lists_nothing(self, tmp_path: Path) -> None:
        assert list_runs(tmp_path / "absent") == []
        assert list_comparisons(tmp_path / "absent") == []

    def test_a_corrupt_run_is_an_error_not_a_crash(self, tmp_path: Path) -> None:
        directory = tmp_path / "runs" / "bad"
        directory.mkdir(parents=True)
        (directory / "run.json").write_text("{}", encoding="utf-8")
        with pytest.raises(StoreError, match="not a valid run report"):
            load_run(directory)
        assert list_runs(tmp_path / "runs") == []

    def test_round_trips_a_comparison(
        self, bootstrapped: SuiteFile, evaluator: Evaluator, tmp_path: Path
    ) -> None:
        baseline = evaluator.run(bootstrapped, "loose", run_dir=tmp_path / "a", run_id="a")
        challenger = evaluator.run(bootstrapped, "locked", run_dir=tmp_path / "b", run_id="b")
        comparison = compare(baseline, challenger)
        path = save_comparison(comparison, tmp_path / "comparisons")
        assert load_comparison(path) == comparison
        assert list_comparisons(tmp_path / "comparisons") == [comparison]

    def test_a_missing_comparison_is_an_error(self, tmp_path: Path) -> None:
        with pytest.raises(StoreError, match="No comparison"):
            load_comparison(tmp_path / "nope.json")


class _CountingEmbedder:
    """Wraps an embedder and counts how often a frame is described."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.calls = 0

    @property
    def name(self) -> str:
        return str(self._inner.name)

    @property
    def identity_dim(self) -> int:
        return int(self._inner.identity_dim)

    def describe(self, image: Any) -> Any:
        self.calls += 1
        return self._inner.describe(image)


class TestManifestCarriesWhatTheRunWasJudgedUnder:
    """A report must be able to draw its own gate lines without the suite file."""

    def test_the_policy_travels_with_the_run(
        self, bootstrapped: SuiteFile, evaluator: Evaluator, tmp_path: Path
    ) -> None:
        result = evaluator.run(bootstrapped, "locked", run_dir=tmp_path / "run", run_id="r1")
        assert result.manifest.policy == bootstrapped.policy
        assert result.manifest.policy.fingerprint() == result.manifest.policy_hash

    def test_it_survives_a_round_trip(
        self, bootstrapped: SuiteFile, evaluator: Evaluator, tmp_path: Path
    ) -> None:
        runs = tmp_path / "runs"
        result = evaluator.run(bootstrapped, "locked", run_dir=runs / "r1", run_id="r1")
        save_run(result, runs)
        assert load_run(runs / "r1").manifest.policy == bootstrapped.policy

    def test_the_identity_space_is_fingerprinted(
        self, bootstrapped: SuiteFile, evaluator: Evaluator, tmp_path: Path
    ) -> None:
        result = evaluator.run(bootstrapped, "locked", run_dir=tmp_path / "run", run_id="r1")
        assert len(result.manifest.identity_space) == 16

    def test_a_backend_without_misses_reports_zero(
        self, bootstrapped: SuiteFile, evaluator: Evaluator, tmp_path: Path
    ) -> None:
        result = evaluator.run(bootstrapped, "locked", run_dir=tmp_path / "run", run_id="r1")
        assert result.manifest.embedder_misses == 0


class TestEachFrameIsDescribedOnce:
    """Identity and content come from one pass; the loop used to make two."""

    def test_one_describe_per_cell(self, bootstrapped: SuiteFile, tmp_path: Path) -> None:
        from identitylock.embeddings import get_embedder

        counting = _CountingEmbedder(get_embedder())
        evaluator = Evaluator(
            provider=build_provider("synthetic"),
            embedder=counting,
            policy=bootstrapped.policy,
        )
        cohort = evaluator.build_cohort(bootstrapped, bootstrapped.cohort_ids())
        before = counting.calls
        result = evaluator.run(
            bootstrapped, "locked", run_dir=tmp_path / "run", cohort=cohort, run_id="r1"
        )
        assert counting.calls - before == len(result.candidates)


class TestIdentitySpaceComparability:
    """Two runs centred differently are not paired, however matched their cells."""

    def test_a_different_space_is_refused(
        self, bootstrapped: SuiteFile, evaluator: Evaluator, tmp_path: Path
    ) -> None:
        baseline = evaluator.run(bootstrapped, "loose", run_dir=tmp_path / "a", run_id="a")
        challenger = evaluator.run(bootstrapped, "locked", run_dir=tmp_path / "b", run_id="b")
        forged = challenger.model_copy(
            update={
                "manifest": challenger.manifest.model_copy(
                    update={"identity_space": "0000000000000000"}
                )
            }
        )
        with pytest.raises(ComparisonError, match="different identity spaces"):
            compare(baseline, forged)

    def test_the_same_space_compares_normally(
        self, bootstrapped: SuiteFile, evaluator: Evaluator, tmp_path: Path
    ) -> None:
        baseline = evaluator.run(bootstrapped, "loose", run_dir=tmp_path / "a", run_id="a")
        challenger = evaluator.run(bootstrapped, "locked", run_dir=tmp_path / "b", run_id="b")
        assert baseline.manifest.identity_space == challenger.manifest.identity_space
        assert compare(baseline, challenger).n_pairs == 4


class TestReferenceRecipeIsResealed:
    """A derived recipe must not inherit the revision of the one it came from."""

    def test_the_revision_is_recomputed(self, suite_file: SuiteFile) -> None:
        base = suite_file.recipe("locked")
        derived = reference_recipe(suite_file)
        assert derived.extra != base.extra
        assert derived.revision != base.revision

    def test_the_revision_matches_its_own_fields(self, suite_file: SuiteFile) -> None:
        derived = reference_recipe(suite_file)
        rebuilt = type(derived).model_validate(derived.model_dump(mode="json"))
        assert rebuilt.revision == derived.revision
