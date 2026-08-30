"""Reports: self-contained, honest, and safe to hand to someone else."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from identitylock.domain.models import RunResult
from identitylock.evaluation import Evaluator, SuiteFile, compare
from identitylock.reporting import render_comparison_report, render_run_report
from identitylock.reporting.charts import delta_bars, drift_chart, histogram, scatter


@pytest.fixture
def result(bootstrapped: SuiteFile, evaluator: Evaluator, tmp_path: Path) -> RunResult:
    return evaluator.run(bootstrapped, "locked", run_dir=tmp_path / "run", run_id="r1")


class TestCharts:
    def test_every_chart_is_well_formed_svg(self) -> None:
        values = [0.4, 0.35, 0.5, 0.2, 0.45, 0.3]
        accepted = [True, True, True, False, True, True]
        charts = [
            drift_chart(values, accepted=accepted, threshold=0.25, slope_per_10=-0.05),
            histogram(values, threshold=0.25),
            scatter(values, values, accepted=accepted, x_threshold=0.25, y_threshold=0.3),
            delta_bars([0.1, -0.05, 0.2], ["a", "b", "c"], ci=(0.01, 0.18)),
        ]
        for svg in charts:
            assert svg.startswith("<svg") and svg.rstrip().endswith("</svg>")
            assert svg.count("<svg") == 1

    def test_empty_input_renders_nothing(self) -> None:
        assert drift_chart([], accepted=[], threshold=0.0, slope_per_10=0.0) == ""
        assert histogram([]) == ""
        assert delta_bars([], []) == ""

    def test_a_constant_series_does_not_divide_by_zero(self) -> None:
        assert histogram([0.5] * 6, threshold=0.5).startswith("<svg")

    def test_bar_titles_are_escaped(self) -> None:
        svg = delta_bars([0.1], ['<script>"x"'], ci=(0.0, 0.2))
        assert "<script>" not in svg
        assert "&lt;script&gt;" in svg


class TestRunReport:
    def test_is_one_self_contained_document(
        self, result: RunResult, bootstrapped: SuiteFile
    ) -> None:
        html = render_run_report(result, policy=bootstrapped.policy)
        assert html.startswith("<!doctype html>")
        # No external fetch of any kind: a report must survive being emailed.
        assert not re.search(r'(src|href)\s*=\s*"(?!data:)https?://', html)
        assert "<script" not in html

    def test_states_the_verdict(self, result: RunResult, bootstrapped: SuiteFile) -> None:
        html = render_run_report(result, policy=bootstrapped.policy)
        assert ("PASS" if result.verdict.passed else "FAIL") in html

    def test_carries_the_disclosure(self, result: RunResult) -> None:
        assert "AI-generated" in render_run_report(result)

    def test_names_every_gate(self, result: RunResult, bootstrapped: SuiteFile) -> None:
        html = render_run_report(result, policy=bootstrapped.policy)
        for gate in result.verdict.gates:
            assert gate.name in html

    def test_states_its_own_limits(self, result: RunResult) -> None:
        html = render_run_report(result)
        assert "does not tell you" in html

    def test_records_provenance(self, result: RunResult) -> None:
        html = render_run_report(result)
        assert result.manifest.recipe_revision in html
        assert result.manifest.embedder in html

    def test_inlines_thumbnails(self, result: RunResult) -> None:
        assert "data:image/jpeg;base64," in render_run_report(result)

    def test_can_skip_thumbnails(self, result: RunResult) -> None:
        html = render_run_report(result, thumbnails=False)
        assert "data:image/jpeg;base64," not in html
        assert len(html) < 60_000

    def test_escapes_character_names(self, result: RunResult) -> None:
        hostile = result.model_copy(
            update={
                "suite": result.suite.model_copy(
                    update={
                        "character": result.suite.character.model_copy(
                            update={"name": '<img src=x onerror="alert(1)">'}
                        )
                    }
                )
            }
        )
        html = render_run_report(hostile, thumbnails=False)
        # The payload survives as inert text: the angle brackets and quotes are
        # escaped, so no tag and no attribute is ever created from it.
        assert "<img" not in html
        assert '"alert(1)"' not in html
        assert "&lt;img src=x onerror=&quot;alert(1)&quot;&gt;" in html


class TestComparisonReport:
    def test_renders_the_outcome_and_the_cells(
        self, bootstrapped: SuiteFile, evaluator: Evaluator, tmp_path: Path
    ) -> None:
        baseline = evaluator.run(bootstrapped, "loose", run_dir=tmp_path / "a", run_id="a")
        challenger = evaluator.run(bootstrapped, "locked", run_dir=tmp_path / "b", run_id="b")
        comparison = compare(baseline, challenger)
        html = render_comparison_report(comparison, baseline=baseline, challenger=challenger)
        assert html.startswith("<!doctype html>")
        assert comparison.verdict.outcome.upper() in html
        for pair in comparison.pairs:
            assert pair.prompt_id in html
        assert not re.search(r'(src|href)\s*=\s*"(?!data:)https?://', html)

    def test_works_without_the_underlying_runs(
        self, bootstrapped: SuiteFile, evaluator: Evaluator, tmp_path: Path
    ) -> None:
        baseline = evaluator.run(bootstrapped, "loose", run_dir=tmp_path / "a", run_id="a")
        challenger = evaluator.run(bootstrapped, "locked", run_dir=tmp_path / "b", run_id="b")
        html = render_comparison_report(compare(baseline, challenger))
        assert "Runs compared" not in html
