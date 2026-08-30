"""Reading and writing runs on disk.

One run is one directory: the images that were scored, the JSON that describes
them, and the HTML report. Nothing in the JSON points outside that directory
except by relative path, so a run can be zipped, moved or archived whole.
"""

from __future__ import annotations

from pathlib import Path

from identitylock.domain.models import Comparison, RunResult

RUN_FILENAME = "run.json"


class StoreError(RuntimeError):
    """A run directory that is not what it claims to be."""


def run_dir(root: Path, run_id: str) -> Path:
    return Path(root) / run_id


def save_run(result: RunResult, root: Path) -> Path:
    """Write ``run.json`` into the run's own directory and return its path."""
    directory = run_dir(root, result.run_id)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / RUN_FILENAME
    path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
    return path


def load_run(path: Path) -> RunResult:
    """Load a run from its directory or directly from its ``run.json``."""
    path = Path(path)
    target = path / RUN_FILENAME if path.is_dir() else path
    if not target.is_file():
        raise StoreError(f"No run at {target}")
    try:
        return RunResult.model_validate_json(target.read_text(encoding="utf-8"))
    except ValueError as error:
        raise StoreError(f"{target} is not a valid run report: {error}") from None


def list_runs(root: Path) -> list[RunResult]:
    """Every run under ``root``, newest first. Unreadable directories are skipped."""
    root = Path(root)
    if not root.is_dir():
        return []
    results: list[RunResult] = []
    for directory in sorted(root.iterdir()):
        if not (directory / RUN_FILENAME).is_file():
            continue
        try:
            results.append(load_run(directory))
        except StoreError:
            continue
    return sorted(results, key=lambda item: item.manifest.created_at, reverse=True)


def save_comparison(comparison: Comparison, root: Path) -> Path:
    directory = Path(root)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{comparison.comparison_id}.json"
    path.write_text(comparison.model_dump_json(indent=2), encoding="utf-8")
    return path


def load_comparison(path: Path) -> Comparison:
    target = Path(path)
    if not target.is_file():
        raise StoreError(f"No comparison at {target}")
    try:
        return Comparison.model_validate_json(target.read_text(encoding="utf-8"))
    except ValueError as error:
        raise StoreError(f"{target} is not a valid comparison: {error}") from None


def list_comparisons(root: Path) -> list[Comparison]:
    directory = Path(root)
    if not directory.is_dir():
        return []
    found: list[Comparison] = []
    for path in sorted(directory.glob("*.json")):
        try:
            found.append(load_comparison(path))
        except StoreError:
            continue
    return found
