"""The README figure renderer, and the states it used to crash in.

Driven as a subprocess, because that is how `make charts` and CI invoke it: an
exception here half-writes the figure set and leaves the README pointing at a
mixture of old and new files.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from identitylock.evaluation import Evaluator, SuiteFile, compare, save_comparison, save_run

SCRIPT = Path(__file__).parent.parent / "scripts" / "render_readme_charts.py"


def _calibration(threshold: float) -> dict[str, object]:
    return {
        "auc": 0.99,
        "eer": 0.04,
        "eer_threshold": threshold,
        "target_far": 0.02,
        "achieved_far": 0.014,
        "frr": 0.042,
        "characters": [],
        "policy": {"identity_min": threshold},
        "warnings": [],
        "scores": {"genuine": [0.8, 0.7, 0.9], "impostor": [0.1, 0.2, 0.0]},
    }


def _render(root: Path, out: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--runs",
            str(root / "runs"),
            "--comparisons",
            str(root / "comparisons"),
            "--calibration",
            str(root / "calibration.json"),
            "--out",
            str(out),
        ],
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.fixture
def rendered(bootstrapped: SuiteFile, evaluator: Evaluator, tmp_path: Path) -> Path:
    """A working directory holding a `locked` run and one comparison."""
    root = tmp_path / "var"
    runs = root / "runs"
    locked = evaluator.run(bootstrapped, "locked", run_dir=runs / "locked", run_id="locked")
    loose = evaluator.run(bootstrapped, "loose", run_dir=runs / "loose", run_id="loose")
    save_run(locked, runs)
    save_run(loose, runs)
    save_comparison(compare(loose, locked), root / "comparisons")
    threshold = locked.manifest.policy.identity_min
    (root / "calibration.json").write_text(json.dumps(_calibration(threshold)), encoding="utf-8")
    return root


class TestChartRenderer:
    def test_writes_both_themes_for_every_figure(self, rendered: Path, tmp_path: Path) -> None:
        out = tmp_path / "assets"
        result = _render(rendered, out)
        assert result.returncode == 0, result.stderr
        names = {path.name for path in out.glob("*.svg")}
        for figure in ("verdicts", "drift", "verification", "comparisons"):
            assert f"{figure}-light.svg" in names
            assert f"{figure}-dark.svg" in names

    def test_the_gate_line_comes_from_the_run(self, rendered: Path, tmp_path: Path) -> None:
        out = tmp_path / "assets"
        _render(rendered, out)
        run = json.loads((rendered / "runs" / "locked" / "run.json").read_text(encoding="utf-8"))
        threshold = run["manifest"]["policy"]["identity_min"]
        body = (out / "verdicts-light.svg").read_text(encoding="utf-8")
        assert f"{threshold:.3f}".rstrip("0").rstrip(".") in body

    def test_no_runs_at_all_says_what_to_do(self, tmp_path: Path) -> None:
        root = tmp_path / "empty"
        root.mkdir()
        (root / "calibration.json").write_text(json.dumps(_calibration(0.1)), encoding="utf-8")
        result = _render(root, tmp_path / "assets")
        assert result.returncode != 0
        assert "make demo" in result.stderr

    def test_a_missing_locked_run_is_explained_not_a_keyerror(
        self, rendered: Path, tmp_path: Path
    ) -> None:
        """Every figure is *about* the locked recipe; without it they'd be mislabelled."""
        for path in (rendered / "runs" / "locked").iterdir():
            if path.is_file():
                path.unlink()
        result = _render(rendered, tmp_path / "assets")
        assert result.returncode != 0
        assert "KeyError" not in result.stderr
        assert "locked" in result.stderr

    def test_no_comparisons_skips_that_figure_instead_of_crashing(
        self, rendered: Path, tmp_path: Path
    ) -> None:
        for path in (rendered / "comparisons").glob("*.json"):
            path.unlink()
        out = tmp_path / "assets"
        result = _render(rendered, out)
        assert result.returncode == 0, result.stderr
        assert "skipped comparisons-light.svg" in result.stdout
        assert not (out / "comparisons-light.svg").exists()
        # The figures that *can* be drawn still are.
        assert (out / "verdicts-light.svg").is_file()
