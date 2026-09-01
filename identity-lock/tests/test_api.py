"""The read-only HTTP surface."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from identitylock.api.app import create_app
from identitylock.evaluation import Evaluator, SuiteFile, compare, save_comparison, save_run


@pytest.fixture
def workdir(bootstrapped: SuiteFile, evaluator: Evaluator, tmp_path: Path) -> Path:
    root = tmp_path / "var"
    runs = root / "runs"
    locked = evaluator.run(bootstrapped, "locked", run_dir=runs / "locked", run_id="locked")
    loose = evaluator.run(bootstrapped, "loose", run_dir=runs / "loose", run_id="loose")
    save_run(locked, runs)
    save_run(loose, runs)
    save_comparison(compare(loose, locked), root / "comparisons")
    return root


@pytest.fixture
def client(workdir: Path) -> Iterator[TestClient]:
    with TestClient(create_app(workdir)) as test_client:
        yield test_client


class TestHealth:
    def test_reports_what_it_is_serving(self, client: TestClient) -> None:
        payload = client.get("/api/health").json()
        assert payload["status"] == "ok"
        assert payload["runs"] == 2
        assert payload["comparisons"] == 1


class TestRuns:
    def test_lists_runs(self, client: TestClient) -> None:
        runs = client.get("/api/runs").json()
        assert {run["run_id"] for run in runs} == {"locked", "loose"}
        assert all("aggregates" in run for run in runs)

    def test_returns_a_run_in_full(self, client: TestClient) -> None:
        payload = client.get("/api/runs/locked").json()
        assert len(payload["candidates"]) == 4
        assert len(payload["gates"]) == 4
        assert payload["suite"]["cohort_ids"] == ["alpha", "beta"]

    def test_candidate_images_resolve(self, client: TestClient) -> None:
        payload = client.get("/api/runs/locked").json()
        url = payload["candidates"][0]["image"]
        response = client.get(url)
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/png"

    def test_unknown_run_is_a_404(self, client: TestClient) -> None:
        assert client.get("/api/runs/ghost").status_code == 404

    def test_serves_the_static_report_when_present(self, client: TestClient, workdir: Path) -> None:
        assert client.get("/api/runs/locked/report").status_code == 404
        (workdir / "runs" / "locked" / "report.html").write_text("<h1>ok</h1>", encoding="utf-8")
        assert client.get("/api/runs/locked/report").status_code == 200


class TestPathTraversal:
    @pytest.mark.parametrize(
        "path",
        [
            "/api/runs/locked/images/..%2F..%2Frun.json",
            "/api/runs/locked/images/%2Fetc%2Fpasswd",
            "/api/runs/..%2F..%2Fetc",
            "/api/runs/locked/images/run.json",
        ],
    )
    def test_is_refused(self, client: TestClient, path: str) -> None:
        assert client.get(path).status_code == 404


class TestComparisons:
    def test_lists_comparisons(self, client: TestClient) -> None:
        payload = client.get("/api/comparisons").json()
        assert len(payload) == 1
        assert payload[0]["outcome"] in {"improvement", "regression", "inconclusive"}

    def test_returns_the_pairs(self, client: TestClient) -> None:
        listed = client.get("/api/comparisons").json()[0]
        payload = client.get(f"/api/comparisons/{listed['comparison_id']}").json()
        assert len(payload["pairs"]) == 4
        assert all("delta" in pair for pair in payload["pairs"])

    def test_unknown_comparison_is_a_404(self, client: TestClient) -> None:
        assert client.get("/api/comparisons/ghost").status_code == 404


class TestEmptyWorkdir:
    def test_serves_an_empty_but_valid_api(self, tmp_path: Path) -> None:
        with TestClient(create_app(tmp_path / "empty")) as client:
            assert client.get("/api/runs").json() == []
            assert client.get("/api/health").json()["runs"] == 0
