"""The command line: exit codes, artefacts, and failure messages."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from identitylock.cli import EXIT_ERROR, EXIT_GATE, EXIT_OK, build_parser, main


@pytest.fixture
def workspace(suite_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(suite_path.parent)
    return suite_path.parent


def _run(*argv: str) -> int:
    return main(list(argv))


class TestParser:
    def test_requires_a_subcommand(self) -> None:
        with pytest.raises(SystemExit):
            build_parser().parse_args([])

    def test_run_requires_a_recipe(self) -> None:
        with pytest.raises(SystemExit):
            build_parser().parse_args(["run", "--suite", "s.yaml"])

    def test_rejects_an_unknown_embedder(self) -> None:
        with pytest.raises(SystemExit):
            build_parser().parse_args(["run", "--recipe", "locked", "--embedder", "telepathy"])


class TestBootstrap:
    def test_renders_the_cohort(self, workspace: Path) -> None:
        assert _run("bootstrap", "--suite", "tiny.yaml") == EXIT_OK
        assert len(list((workspace / "references" / "alpha").glob("*.png"))) == 4
        assert len(list((workspace / "references" / "beta").glob("*.png"))) == 4


class TestRun:
    def test_writes_a_run_and_a_report(self, workspace: Path) -> None:
        _run("bootstrap", "--suite", "tiny.yaml")
        assert (
            _run("run", "--suite", "tiny.yaml", "--recipe", "locked", "--run-id", "r1") == EXIT_OK
        )
        assert (workspace / "var" / "runs" / "r1" / "run.json").is_file()
        assert (workspace / "var" / "runs" / "r1" / "report.html").is_file()
        assert len(list((workspace / "var" / "runs" / "r1" / "images").glob("*.png"))) == 4

    def test_can_skip_the_report(self, workspace: Path) -> None:
        _run("bootstrap", "--suite", "tiny.yaml")
        _run("run", "--suite", "tiny.yaml", "--recipe", "locked", "--run-id", "r1", "--no-report")
        assert not (workspace / "var" / "runs" / "r1" / "report.html").exists()

    def test_derives_a_run_id_when_none_is_given(self, workspace: Path) -> None:
        _run("bootstrap", "--suite", "tiny.yaml")
        assert _run("run", "--suite", "tiny.yaml", "--recipe", "locked") == EXIT_OK
        directories = [path for path in (workspace / "var" / "runs").iterdir() if path.is_dir()]
        assert len(directories) == 1
        assert directories[0].name.startswith("tiny.locked.")
        assert (directories[0] / "images").is_dir()

    def test_gate_flag_fails_a_failing_run(self, workspace: Path) -> None:
        _run("bootstrap", "--suite", "tiny.yaml")
        strict = (
            (workspace / "tiny.yaml")
            .read_text()
            .replace("identity_min: -1.0", "identity_min: 0.99")
            .replace("consistency_rate_min: 0.0", "consistency_rate_min: 0.9")
        )
        (workspace / "strict.yaml").write_text(strict, encoding="utf-8")
        assert (
            _run("run", "--suite", "strict.yaml", "--recipe", "locked", "--run-id", "s1") == EXIT_OK
        )
        assert (
            _run("run", "--suite", "strict.yaml", "--recipe", "locked", "--run-id", "s2", "--gate")
            == EXIT_GATE
        )

    def test_missing_references_are_reported_not_crashed(
        self, workspace: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert _run("run", "--suite", "tiny.yaml", "--recipe", "locked") == EXIT_ERROR
        assert "identitylock bootstrap" in capsys.readouterr().err

    def test_an_unknown_recipe_is_reported(
        self, workspace: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _run("bootstrap", "--suite", "tiny.yaml")
        assert _run("run", "--suite", "tiny.yaml", "--recipe", "ghost") == EXIT_ERROR
        assert "Unknown recipe" in capsys.readouterr().err

    def test_a_missing_suite_is_reported(
        self, workspace: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert _run("run", "--suite", "absent.yaml", "--recipe", "locked") == EXIT_ERROR
        assert "not found" in capsys.readouterr().err


class TestCompare:
    def _two_runs(self, workspace: Path) -> tuple[Path, Path]:
        _run("bootstrap", "--suite", "tiny.yaml")
        _run("run", "--suite", "tiny.yaml", "--recipe", "loose", "--run-id", "base", "--no-report")
        _run("run", "--suite", "tiny.yaml", "--recipe", "locked", "--run-id", "chal", "--no-report")
        runs = workspace / "var" / "runs"
        return runs / "base", runs / "chal"

    def test_writes_a_comparison_and_a_report(self, workspace: Path) -> None:
        baseline, challenger = self._two_runs(workspace)
        code = _run("compare", "--baseline", str(baseline), "--challenger", str(challenger))
        assert code == EXIT_OK
        comparisons = list((workspace / "var" / "comparisons").glob("*.json"))
        reports = list((workspace / "var" / "comparisons").glob("*.html"))
        assert len(comparisons) == 1
        assert len(reports) == 1

    def test_reports_an_incomparable_pair(
        self, workspace: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        baseline, _ = self._two_runs(workspace)
        assert (
            _run("compare", "--baseline", str(baseline), "--challenger", str(baseline))
            == EXIT_ERROR
        )
        assert "same recipe revision" in capsys.readouterr().err

    def test_a_missing_run_is_reported(
        self, workspace: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        baseline, _ = self._two_runs(workspace)
        assert (
            _run("compare", "--baseline", str(baseline), "--challenger", "var/runs/ghost")
            == EXIT_ERROR
        )
        assert "No run at" in capsys.readouterr().err


class TestCalibrate:
    def test_json_output_is_machine_readable(
        self, workspace: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _run("bootstrap", "--suite", "tiny.yaml")
        capsys.readouterr()  # drop the bootstrap chatter
        assert _run("calibrate", "--suite", "tiny.yaml", "--seeds", "2", "--json") == EXIT_OK
        payload = json.loads(capsys.readouterr().out)
        assert 0.0 <= payload["auc"] <= 1.0
        assert "identity_min" in payload["policy"]
        assert isinstance(payload["characters"], list)
        # The distributions travel with the summary, so a chart or a second pass
        # never has to re-render the validation set to see them.
        genuine = payload["scores"]["genuine"]
        impostor = payload["scores"]["impostor"]
        assert len(genuine) > 0
        # One impostor score per frame per *other* character: the tiny cohort has
        # two, so the two lists are the same length here and diverge for bigger ones.
        assert len(impostor) == len(genuine) * (len(payload["characters"]) - 1)

    def test_write_updates_the_suite_without_losing_comments(self, workspace: Path) -> None:
        _run("bootstrap", "--suite", "tiny.yaml")
        before = (workspace / "tiny.yaml").read_text()
        assert _run("calibrate", "--suite", "tiny.yaml", "--seeds", "2", "--write") == EXIT_OK
        after = (workspace / "tiny.yaml").read_text()
        assert after != before
        assert "# " not in before or after.count("#") == before.count("#")
        assert "identity_min:" in after
        assert "-1.0" not in after.split("policy:")[1]

    def test_refuses_to_calibrate_without_references(
        self, workspace: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert _run("calibrate", "--suite", "tiny.yaml") == EXIT_ERROR
        assert "bootstrap" in capsys.readouterr().out

    def test_json_mode_keeps_stdout_clean(
        self, workspace: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _run("bootstrap", "--suite", "tiny.yaml")
        capsys.readouterr()
        _run("calibrate", "--suite", "tiny.yaml", "--seeds", "2", "--json")
        captured = capsys.readouterr()
        assert captured.out.lstrip().startswith("{")
        assert "Calibrating" in captured.err


class TestReportAndList:
    def test_regenerates_a_report(self, workspace: Path) -> None:
        _run("bootstrap", "--suite", "tiny.yaml")
        _run("run", "--suite", "tiny.yaml", "--recipe", "locked", "--run-id", "r1", "--no-report")
        target = workspace / "fresh.html"
        assert (
            _run("report", "--run", "var/runs/r1", "--suite", "tiny.yaml", "--output", str(target))
            == EXIT_OK
        )
        assert target.read_text(encoding="utf-8").startswith("<!doctype html>")

    def test_lists_runs(self, workspace: Path, capsys: pytest.CaptureFixture[str]) -> None:
        _run("bootstrap", "--suite", "tiny.yaml")
        _run("run", "--suite", "tiny.yaml", "--recipe", "locked", "--run-id", "r1", "--no-report")
        assert _run("runs") == EXIT_OK
        assert "r1" in capsys.readouterr().out

    def test_lists_nothing_gracefully(
        self, workspace: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert _run("runs") == EXIT_OK
        assert "no runs" in capsys.readouterr().out


class TestDemo:
    def test_runs_everything_it_can_find(self, workspace: Path) -> None:
        assert _run("demo", "--suite", "tiny.yaml") == EXIT_OK
        runs = workspace / "var" / "runs"
        assert (runs / "tiny.locked" / "report.html").is_file()


class TestReportDestination:
    """`--run` accepts a directory or the run.json inside it; both are documented."""

    def _run_once(self, workspace: Path) -> None:
        _run("bootstrap", "--suite", "tiny.yaml")
        _run("run", "--suite", "tiny.yaml", "--recipe", "locked", "--run-id", "r1", "--no-report")

    def test_a_directory_target_writes_inside_it(self, workspace: Path) -> None:
        self._run_once(workspace)
        assert _run("report", "--run", "var/runs/r1") == EXIT_OK
        assert (workspace / "var" / "runs" / "r1" / "report.html").is_file()

    def test_a_run_json_target_writes_beside_it(self, workspace: Path) -> None:
        """This used to raise FileExistsError from mkdir on `run.json/report.html`."""
        self._run_once(workspace)
        assert _run("report", "--run", "var/runs/r1/run.json") == EXIT_OK
        assert (workspace / "var" / "runs" / "r1" / "report.html").is_file()

    def test_the_gates_are_drawn_without_being_handed_the_suite(self, workspace: Path) -> None:
        self._run_once(workspace)
        target = workspace / "no-suite.html"
        assert _run("report", "--run", "var/runs/r1", "--output", str(target)) == EXIT_OK
        body = target.read_text(encoding="utf-8")
        assert "identity &#8805;" in body


class TestCalibrateWriteIsHonest:
    """--write must not claim to have written a file it did not touch."""

    def test_a_suite_without_policy_lines_is_reported(
        self, workspace: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        source = (workspace / "tiny.yaml").read_text()
        trimmed = source[: source.index("policy:")]
        (workspace / "bare.yaml").write_text(trimmed, encoding="utf-8")
        before = (workspace / "bare.yaml").read_text()

        _run("bootstrap", "--suite", "bare.yaml")
        capsys.readouterr()
        assert _run("calibrate", "--suite", "bare.yaml", "--seeds", "2", "--write") == EXIT_OK

        out = capsys.readouterr().out
        assert "not written" in out
        assert "identity_min" in out
        assert (workspace / "bare.yaml").read_text() == before

    def test_present_keys_are_named_as_updated(
        self, workspace: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _run("bootstrap", "--suite", "tiny.yaml")
        capsys.readouterr()
        assert _run("calibrate", "--suite", "tiny.yaml", "--seeds", "2", "--write") == EXIT_OK
        out = capsys.readouterr().out
        assert "updated in tiny.yaml" in out
        assert "not written" not in out
