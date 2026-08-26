"""CLI smoke tests — every command runs, and the generating ones stay offline."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from seedance.cli import app

runner = CliRunner()


@pytest.fixture(autouse=True)
def _isolated_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEEDANCE_OUTPUT_DIR", str(tmp_path / "out"))
    monkeypatch.setenv("SEEDANCE_DB_PATH", str(tmp_path / "seedance.db"))
    monkeypatch.setenv("SEEDANCE_POLL_INTERVAL_S", "0")
    monkeypatch.setenv("SEEDANCE_DRAFT_PROVIDER", "fake")
    monkeypatch.setenv("SEEDANCE_FINAL_PROVIDER", "fake")
    monkeypatch.setenv("ARK_API_KEY", "ark-test-key")


def test_rates_prices_a_clip_everywhere() -> None:
    result = runner.invoke(app, ["rates", "--duration", "5", "--resolution", "720p"])
    assert result.exit_code == 0, result.output
    assert "WaveSpeed" in result.output
    assert "$1.156" in result.output or "$1.15" in result.output


def test_rates_can_be_limited_to_callable_adapters() -> None:
    result = runner.invoke(app, ["rates", "--adapters-only"])
    assert result.exit_code == 0
    assert "fal" not in result.output.lower()


def test_estimate_totals_a_batch() -> None:
    result = runner.invoke(app, ["estimate", "a prompt", "--variants", "3", "--resolution", "480p"])
    assert result.exit_code == 0, result.output
    assert "total $1.54" in result.output


def test_estimate_refuses_an_unpriced_combination() -> None:
    result = runner.invoke(
        app, ["estimate", "x", "--provider", "wavespeed_turbo", "--resolution", "1080p"]
    )
    assert result.exit_code == 1
    assert "no published rate for 1080p" in result.output


def test_dry_run_sends_nothing_and_masks_the_key() -> None:
    result = runner.invoke(
        app, ["draft", "a prompt", "--provider", "modelark", "--dry-run", "-n", "2"]
    )
    assert result.exit_code == 0, result.output
    assert "contents/generations/tasks" in result.output
    assert "ark-test-key" not in result.output
    assert "***" in result.output


def test_draft_then_final(tmp_path: Path) -> None:
    drafted = runner.invoke(app, ["draft", "a test clip", "-n", "2", "--provider", "fake"])
    assert drafted.exit_code == 0, drafted.output
    assert "succeeded" in drafted.output
    assert "batch total: $1.028" in drafted.output

    outputs = list((tmp_path / "out").rglob("draft-*.mp4"))
    assert len(outputs) == 2

    finished = runner.invoke(
        app, ["final", "--pick", "1", "--provider", "fake", "--resolution", "720p"]
    )
    assert finished.exit_code == 0, finished.output
    assert list((tmp_path / "out").rglob("final-*.mp4"))


def test_final_without_a_draft_run_explains_itself() -> None:
    result = runner.invoke(app, ["final", "--pick", "1"])
    assert result.exit_code == 1
    assert "run `seedance draft` first" in result.output


def test_budget_blocks_a_run_and_reports_it() -> None:
    assert runner.invoke(app, ["budget", "--daily", "0.10"]).exit_code == 0

    blocked = runner.invoke(app, ["draft", "a test clip", "-n", "2", "--provider", "fake"])
    assert blocked.exit_code == 1
    assert "budget would be exceeded" in blocked.output

    forced = runner.invoke(
        app, ["draft", "a test clip", "-n", "1", "--provider", "fake", "--force"]
    )
    assert forced.exit_code == 0, forced.output


def test_spend_and_jobs_report_the_run() -> None:
    runner.invoke(app, ["draft", "a test clip", "-n", "1", "--provider", "fake"])

    spend = runner.invoke(app, ["spend"])
    assert spend.exit_code == 0
    assert "daily" in spend.output

    jobs = runner.invoke(app, ["jobs"])
    assert jobs.exit_code == 0
    assert "fake" in jobs.output


def test_providers_shows_which_keys_are_present() -> None:
    result = runner.invoke(app, ["providers"])
    assert result.exit_code == 0
    assert "modelark" in result.output
