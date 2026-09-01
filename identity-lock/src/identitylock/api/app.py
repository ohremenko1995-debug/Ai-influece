"""Read-only HTTP API over stored runs, plus the dashboard that consumes it.

Read-only on purpose. The API never generates, never scores and never mutates a
run: everything it serves was produced by the CLI and written to disk. A dashboard
that can start a GPU job is a different product with a different threat model, and
this one is meant to be safe to point at a directory and open in a browser.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from identitylock import REPORT_SCHEMA_VERSION, __version__
from identitylock.domain.models import Comparison, RunResult
from identitylock.evaluation.store import (
    RUN_FILENAME,
    list_comparisons,
    list_runs,
    load_run,
)

_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}


def _summarise(result: RunResult) -> dict[str, Any]:
    aggregates = result.aggregates
    return {
        "run_id": result.run_id,
        "label": result.label,
        "suite_id": result.suite.id,
        "character": {
            "id": result.suite.character.id,
            "name": result.suite.character.name,
            "disclosure": result.suite.character.disclosure,
        },
        "recipe": {
            "id": result.suite.recipe.id,
            "name": result.suite.recipe.name,
            "revision": result.suite.recipe.revision,
        },
        "created_at": result.manifest.created_at.isoformat(),
        "embedder": result.manifest.embedder,
        "provider": result.manifest.provider,
        "passed": result.verdict.passed,
        "failed_gates": list(result.verdict.failed_gates),
        "aggregates": aggregates.model_dump(),
        "n_selected": len(result.selected),
    }


def _detail(result: RunResult, run_root: Path) -> dict[str, Any]:
    payload = _summarise(result)
    payload["gates"] = [gate.model_dump() for gate in result.verdict.gates]
    # The thresholds the run was actually judged under. Without them the dashboard
    # had to infer the candidate gate from which frames were rejected, which
    # disagreed with the static report whenever nothing was rejected for identity.
    payload["policy"] = result.manifest.policy.model_dump(mode="json")
    payload["manifest"] = result.manifest.model_dump(mode="json")
    payload["suite"] = {
        "id": result.suite.id,
        "description": result.suite.description,
        "cohort_ids": list(result.suite.cohort_ids),
        "prompts": [prompt.model_dump() for prompt in result.suite.prompts],
        "seeds": list(result.suite.seeds),
        "recipe": result.suite.recipe.model_dump(mode="json"),
    }
    payload["candidates"] = [
        {
            "id": item.candidate.id,
            "prompt_id": item.candidate.prompt_id,
            "prompt": item.candidate.prompt,
            "seed": item.candidate.seed,
            "decision": item.decision,
            "selected": item.selected,
            "rejections": list(item.rejections),
            "metrics": item.metrics.model_dump(),
            "image": (
                f"/api/runs/{result.run_id}/images/{Path(item.candidate.image_path).name}"
                if _is_under(Path(item.candidate.image_path), run_root)
                else None
            ),
        }
        for item in result.candidates
    ]
    return payload


def _is_under(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except (ValueError, OSError):
        return False
    return True


def create_app(workdir: Path) -> FastAPI:
    """Build the application over a working directory produced by the CLI."""
    workdir = Path(workdir)
    runs_root = workdir / "runs"
    comparisons_root = workdir / "comparisons"

    app = FastAPI(
        title="Identity Lock",
        version=__version__,
        description="Read-only view over stored identity-consistency runs.",
    )
    # The dashboard is normally served from this same origin. CORS is opened only
    # for localhost so `vite dev` on another port can talk to a running API during
    # development; nothing here is a credentialed endpoint.
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"http://(localhost|127\.0\.0\.1):\d+",
        allow_methods=["GET"],
        allow_headers=["*"],
    )

    def _run_dir(run_id: str) -> Path:
        directory = runs_root / run_id
        if not _is_under(directory, runs_root) or not (directory / RUN_FILENAME).is_file():
            raise HTTPException(status_code=404, detail=f"No run '{run_id}'")
        return directory

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "version": __version__,
            "report_schema_version": REPORT_SCHEMA_VERSION,
            "workdir": str(workdir.resolve()),
            "runs": len(list_runs(runs_root)),
            "comparisons": len(list_comparisons(comparisons_root)),
        }

    @app.get("/api/runs")
    def runs() -> list[dict[str, Any]]:
        return [_summarise(result) for result in list_runs(runs_root)]

    @app.get("/api/runs/{run_id}")
    def run_detail(run_id: str) -> dict[str, Any]:
        directory = _run_dir(run_id)
        return _detail(load_run(directory), directory)

    @app.get("/api/runs/{run_id}/images/{name}")
    def run_image(run_id: str, name: str) -> FileResponse:
        images = _run_dir(run_id) / "images"
        target = images / Path(name).name
        if target.suffix.lower() not in _IMAGE_SUFFIXES or not _is_under(target, images):
            raise HTTPException(status_code=404, detail="No such image")
        if not target.is_file():
            raise HTTPException(status_code=404, detail="No such image")
        return FileResponse(target)

    @app.get("/api/runs/{run_id}/report")
    def run_report(run_id: str) -> HTMLResponse:
        report = _run_dir(run_id) / "report.html"
        if not report.is_file():
            raise HTTPException(status_code=404, detail="No report for this run")
        return HTMLResponse(report.read_text(encoding="utf-8"))

    @app.get("/api/comparisons")
    def comparisons() -> list[dict[str, Any]]:
        return [_comparison_payload(item) for item in list_comparisons(comparisons_root)]

    @app.get("/api/comparisons/{comparison_id}")
    def comparison_detail(comparison_id: str) -> dict[str, Any]:
        for item in list_comparisons(comparisons_root):
            if item.comparison_id == comparison_id:
                payload = _comparison_payload(item)
                payload["pairs"] = [
                    {**pair.model_dump(), "delta": pair.delta} for pair in item.pairs
                ]
                payload["gates"] = [gate.model_dump() for gate in item.verdict.gates]
                return payload
        raise HTTPException(status_code=404, detail=f"No comparison '{comparison_id}'")

    static_dir = Path(__file__).parent / "static"
    if static_dir.is_dir():
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="dashboard")
    else:  # pragma: no cover - only when the dashboard was not built

        @app.get("/")
        def missing_dashboard() -> HTMLResponse:
            return HTMLResponse(
                "<h1>Identity Lock</h1><p>The dashboard bundle is not built. "
                "Run <code>make web</code>, or use the API under <code>/api</code>.</p>",
                status_code=200,
            )

    return app


def _comparison_payload(comparison: Comparison) -> dict[str, Any]:
    return {
        "comparison_id": comparison.comparison_id,
        "metric": comparison.metric,
        "baseline_run_id": comparison.baseline_run_id,
        "baseline_label": comparison.baseline_label,
        "challenger_run_id": comparison.challenger_run_id,
        "challenger_label": comparison.challenger_label,
        "win_rate": comparison.win_rate,
        "mean_delta": comparison.mean_delta,
        "ci_low": comparison.ci_low,
        "ci_high": comparison.ci_high,
        "effect_size": comparison.effect_size,
        "n_pairs": comparison.n_pairs,
        "outcome": comparison.verdict.outcome,
        "rationale": comparison.verdict.rationale,
    }
