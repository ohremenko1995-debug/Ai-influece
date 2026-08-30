"""Command line interface.

Argparse rather than a CLI framework: the command surface is small, the typing is
exact, and one fewer runtime dependency matters for a tool people are meant to
drop into a CI job.

Every command that can fail a gate returns a meaningful exit code, because the
whole point of a harness is that a machine can read its answer:

* ``0`` — the run passed, or the comparison was not a regression
* ``1`` — a gate failed (only with ``--gate``), or a comparison found a regression
* ``2`` — the command could not run at all: bad suite, missing references, provider error
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TextIO

from identitylock import __version__
from identitylock.domain.models import Comparison, RunResult
from identitylock.domain.policy import Policy
from identitylock.embeddings import DEFAULT_EMBEDDER, get_embedder, registered
from identitylock.evaluation import (
    ComparisonError,
    EvaluationError,
    Evaluator,
    SuiteFileError,
    compare,
    list_runs,
    load_run,
    load_suite_file,
    render_references,
    save_comparison,
    save_run,
)
from identitylock.evaluation.runner import Progress, reference_paths
from identitylock.evaluation.store import StoreError
from identitylock.evaluation.suite import SuiteFile
from identitylock.evaluation.validation import render_validation
from identitylock.imaging.loader import load_image
from identitylock.metrics.calibration import calibrate_from_validation
from identitylock.metrics.identity import build_profile
from identitylock.metrics.space import IdentitySpace
from identitylock.providers import build_provider
from identitylock.providers.base import GenerationProvider, ProviderError
from identitylock.reporting import render_comparison_report, render_run_report

EXIT_OK = 0
EXIT_GATE = 1
EXIT_ERROR = 2

DEFAULT_WORKDIR = Path("var")
DEMO_RECIPES = ("locked", "baseline", "drifting", "overcooked")


# --------------------------------------------------------------------------- #
# Terminal helpers
# --------------------------------------------------------------------------- #


def _colour_enabled(stream: TextIO) -> bool:
    if os.environ.get("NO_COLOR") is not None:
        return False
    return bool(getattr(stream, "isatty", lambda: False)())


class Console:
    """Minimal styled output. Falls back to plain text when piped."""

    def __init__(self, stream: TextIO | None = None) -> None:
        self.stream = stream or sys.stdout
        self._colour = _colour_enabled(self.stream)

    def _wrap(self, text: str, code: str) -> str:
        return f"\033[{code}m{text}\033[0m" if self._colour else text

    def write(self, text: str = "") -> None:
        print(text, file=self.stream)

    def title(self, text: str) -> None:
        self.write(self._wrap(text, "1"))

    def muted(self, text: str) -> None:
        self.write(self._wrap(text, "2"))

    def ok(self, text: str) -> str:
        return self._wrap(text, "32")

    def bad(self, text: str) -> str:
        return self._wrap(text, "31")

    def warn(self, text: str) -> str:
        return self._wrap(text, "33")

    def verdict(self, passed: bool) -> str:
        return self.ok("PASS") if passed else self.bad("FAIL")


def _progress(console: Console) -> Progress:
    """A one-line progress ticker on a terminal, a single summary line when piped."""
    interactive = bool(getattr(console.stream, "isatty", lambda: False)())

    def report(done: int, total: int, label: str) -> None:
        if interactive:
            end = "\n" if done == total else ""
            print(
                f"\r  {done}/{total}  {label[:58]:<58}",
                end=end,
                file=console.stream,
                flush=True,
            )
        elif done == total:
            print(f"  generated {total} frames", file=console.stream)

    return report


# --------------------------------------------------------------------------- #
# Shared plumbing
# --------------------------------------------------------------------------- #


def _make_provider(args: argparse.Namespace) -> GenerationProvider:
    if args.provider == "directory":
        return build_provider("directory", root=args.images)
    if args.provider == "comfyui":
        return build_provider("comfyui", base_url=args.comfyui, workflow_path=args.workflow)
    return build_provider("synthetic")


def _load(path: Path) -> SuiteFile:
    return load_suite_file(path)


def _evaluator(suite_file: SuiteFile, args: argparse.Namespace, policy: Policy) -> Evaluator:
    return Evaluator(
        provider=_make_provider(args),
        embedder=get_embedder(args.embedder),
        policy=policy,
        select_k=suite_file.select_k,
        select_lambda=suite_file.select_lambda,
    )


def _write_report(result: RunResult, policy: Policy, directory: Path) -> Path:
    path = directory / "report.html"
    path.write_text(render_run_report(result, policy=policy), encoding="utf-8")
    return path


def _print_run(console: Console, result: RunResult) -> None:
    aggregates = result.aggregates
    console.write()
    console.write(f"  {console.verdict(result.verdict.passed)}  {result.label}  [{result.run_id}]")
    console.write(
        f"    identity {aggregates.identity_mean:+.3f} "
        f"(95% CI {aggregates.identity_ci_low:+.3f}..{aggregates.identity_ci_high:+.3f}), "
        f"p05 {aggregates.identity_p05:+.3f}"
    )
    margin = "n/a" if aggregates.margin_mean is None else f"{aggregates.margin_mean:+.3f}"
    console.write(
        f"    margin {margin}   technical {aggregates.technical_mean:.3f}   "
        f"diversity {aggregates.diversity:.3f}"
    )
    console.write(
        f"    accepted {aggregates.n_accepted}/{aggregates.n_total}   "
        f"drift {aggregates.drift_slope:+.4f}/10 (p={aggregates.drift_p_value:.3f})"
    )
    for gate in result.verdict.gates:
        mark = console.ok("ok  ") if gate.passed else console.bad("FAIL")
        observed = "—" if gate.observed is None else f"{gate.observed:.4f}"
        threshold = "—" if gate.threshold is None else f"{gate.threshold:.4f}"
        console.write(f"      {mark} {gate.name:<18} {observed:>9}  vs  {threshold}")


def _print_comparison(console: Console, comparison: Comparison) -> None:
    outcome = comparison.verdict.outcome
    styled = {
        "improvement": console.ok,
        "regression": console.bad,
        "inconclusive": console.warn,
    }[outcome](outcome.upper())
    console.write()
    console.write(f"  {styled}  {comparison.challenger_label} vs {comparison.baseline_label}")
    console.write(
        f"    metric {comparison.metric}   win rate {comparison.win_rate:.0%}   "
        f"mean {comparison.mean_delta:+.4f}   "
        f"CI [{comparison.ci_low:+.4f}, {comparison.ci_high:+.4f}]   "
        f"effect {comparison.effect_size:+.3f}"
    )
    console.write(f"    {comparison.verdict.rationale}")


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #


def cmd_bootstrap(args: argparse.Namespace) -> int:
    console = Console()
    suite_file = _load(args.suite)
    provider = _make_provider(args)
    console.title(f"Rendering reference sets for suite '{suite_file.id}'")
    rendered = render_references(suite_file, provider, count=args.count, force=args.force)
    for character_id, paths in rendered.items():
        console.write(f"  {character_id:<10} {len(paths):>3} frames  {paths[0].parent}")
    console.muted(
        "\nReferences are the yardstick every later number is measured against. "
        "Replace them with curated frames when you have them."
    )
    return EXIT_OK


def cmd_calibrate(args: argparse.Namespace) -> int:
    # With --json, stdout carries the document and nothing else, so the command
    # can be piped straight into jq. Progress still goes somewhere a human can see.
    console = Console(sys.stderr if args.json else sys.stdout)
    suite_file = _load(args.suite)
    provider = _make_provider(args)
    embedder = get_embedder(args.embedder)

    console.title(f"Calibrating '{suite_file.id}' with {embedder.name}")
    missing = [
        character_id
        for character_id in suite_file.cohort_ids()
        if not reference_paths(suite_file.reference_dir(character_id))
    ]
    if missing:
        console.write(
            f"  no reference images for: {', '.join(missing)} — run `identitylock bootstrap` first"
        )
        return EXIT_ERROR

    references = {
        character_id: [
            embedder.describe(load_image(path)).identity
            for path in reference_paths(suite_file.reference_dir(character_id))
        ]
        for character_id in suite_file.cohort_ids()
    }
    space = IdentitySpace.fit([vector for vectors in references.values() for vector in vectors])
    profiles = [
        build_profile(character_id, space.project_all(vectors))
        for character_id, vectors in references.items()
    ]

    console.muted(f"  rendering validation frames on seeds 7000+ ({args.seeds} per prompt)")
    validation_paths = render_validation(
        suite_file,
        provider,
        recipe_id=args.recipe,
        output_root=args.out / "validation",
        seeds=args.seeds,
    )
    validation = {
        character_id: space.project_all(
            [embedder.describe(load_image(path)).identity for path in paths]
        )
        for character_id, paths in validation_paths.items()
    }

    calibration, curve = calibrate_from_validation(profiles, validation, target_far=args.far)
    far, frr = curve.rates_at(calibration.suggested.identity_min)

    if args.json:
        payload: dict[str, object] = {
            "auc": curve.auc,
            "eer": curve.eer,
            "eer_threshold": curve.eer_threshold,
            "target_far": args.far,
            "achieved_far": far,
            "frr": frr,
            "characters": calibration.table(),
            "policy": calibration.suggested.model_dump(),
            "warnings": list(calibration.warnings),
        }
        print(json.dumps(payload, indent=2))
        return EXIT_OK

    console.write()
    console.write(
        f"  {'character':<10}{'refs':>5}{'coherence':>11}{'loo mean':>10}"
        f"{'impostor':>10}{'separation':>12}"
    )
    for row in calibration.table():
        console.write(
            f"  {row['character']!s:<10}{row['references']!s:>5}{row['coherence']!s:>11}"
            f"{row['loo_mean']!s:>10}{row['impostor_max']!s:>10}{row['separation']!s:>12}"
        )
    console.write()
    console.write(
        f"  verification AUC {curve.auc:.4f}   EER {curve.eer:.2%} at {curve.eer_threshold:+.4f}"
    )
    console.write(
        f"  operating point: FAR target {args.far:.1%} -> achieved {far:.2%}, FRR {frr:.2%}"
    )
    console.write()
    console.title("  suggested policy")
    for key, value in calibration.suggested.model_dump().items():
        console.write(f"    {key:<22} {value}")
    for warning in calibration.warnings:
        console.write(f"  {console.warn('warning')} {warning}")

    if args.write:
        _rewrite_policy(args.suite, calibration.suggested)
        console.write(f"\n  written into {args.suite}")
    else:
        console.muted("\n  re-run with --write to store these thresholds in the suite file")
    return EXIT_OK


def _rewrite_policy(path: Path, policy: Policy) -> None:
    """Replace the four calibrated values in a suite file, leaving the rest alone.

    A line edit rather than a YAML round-trip: rewriting the document would strip
    every comment in it, and the comments are where the reasoning lives.
    """
    calibrated = {
        "identity_min": policy.identity_min,
        "identity_p05_min": policy.identity_p05_min,
        "margin_min": policy.margin_min,
        "consistency_rate_min": policy.consistency_rate_min,
    }
    lines = path.read_text(encoding="utf-8").splitlines()
    for index, line in enumerate(lines):
        stripped = line.strip()
        for key, value in calibrated.items():
            if stripped.startswith(f"{key}:"):
                indent = line[: len(line) - len(line.lstrip())]
                lines[index] = f"{indent}{key}: {value}"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def cmd_run(args: argparse.Namespace) -> int:
    console = Console()
    suite_file = _load(args.suite)
    policy = suite_file.policy
    evaluator = _evaluator(suite_file, args, policy)

    runs_root = args.out / "runs"
    suite = suite_file.to_suite(args.recipe)
    console.title(f"Running suite '{suite.id}' under recipe '{args.recipe}'")
    console.muted(
        f"  {len(suite.plan)} cells · provider {args.provider} · embedder {args.embedder}"
    )

    cohort = evaluator.build_cohort(suite_file, suite.cohort_ids)
    run_id = args.run_id or None
    result = evaluator.run(
        suite_file,
        args.recipe,
        run_dir=runs_root / (run_id or "pending"),
        cohort=cohort,
        run_id=run_id,
        progress=_progress(console),
    )
    if run_id is None:
        # The run id embeds a timestamp only known after generation; move the
        # images under it so the directory and the id always agree.
        pending = runs_root / "pending"
        final = runs_root / result.run_id
        final.parent.mkdir(parents=True, exist_ok=True)
        if pending.exists():
            pending.rename(final)
        result = result.model_copy(
            update={
                "candidates": tuple(
                    item.model_copy(
                        update={
                            "candidate": item.candidate.model_copy(
                                update={
                                    "image_path": final / "images" / item.candidate.image_path.name
                                }
                            )
                        }
                    )
                    for item in result.candidates
                )
            }
        )

    directory = runs_root / result.run_id
    save_run(result, runs_root)
    _print_run(console, result)

    if not args.no_report:
        report = _write_report(result, policy, directory)
        console.write(f"\n  report  {report}")
    console.write(f"  data    {directory / 'run.json'}")

    return EXIT_GATE if (args.gate and not result.verdict.passed) else EXIT_OK


def cmd_compare(args: argparse.Namespace) -> int:
    console = Console()
    baseline = load_run(args.baseline)
    challenger = load_run(args.challenger)
    policy = None
    if args.suite is not None:
        policy = _load(args.suite).comparison_policy

    comparison = compare(baseline, challenger, metric=args.metric, policy=policy)
    _print_comparison(console, comparison)

    root = args.out / "comparisons"
    path = save_comparison(comparison, root)
    report = root / f"{comparison.comparison_id}.html"
    report.write_text(
        render_comparison_report(comparison, baseline=baseline, challenger=challenger),
        encoding="utf-8",
    )
    console.write(f"\n  report  {report}")
    console.write(f"  data    {path}")

    if args.gate and comparison.verdict.outcome == "regression":
        return EXIT_GATE
    return EXIT_OK


def cmd_demo(args: argparse.Namespace) -> int:
    """Everything, from a clean checkout, in one command."""
    console = Console()
    suite_file = _load(args.suite)
    provider = build_provider("synthetic")

    console.title("1/4  Rendering reference sets")
    render_references(suite_file, provider)

    console.title("2/4  Running every recipe")
    evaluator = Evaluator(
        provider=provider,
        embedder=get_embedder(args.embedder),
        policy=suite_file.policy,
        select_k=suite_file.select_k,
        select_lambda=suite_file.select_lambda,
    )
    cohort = evaluator.build_cohort(suite_file, suite_file.cohort_ids())
    runs_root = args.out / "runs"
    results: dict[str, RunResult] = {}
    for recipe_id in DEMO_RECIPES:
        if recipe_id not in suite_file.recipes:
            continue
        run_id = f"{suite_file.id}.{recipe_id}"
        result = evaluator.run(
            suite_file,
            recipe_id,
            run_dir=runs_root / run_id,
            cohort=cohort,
            run_id=run_id,
            progress=_progress(console),
        )
        save_run(result, runs_root)
        _write_report(result, suite_file.policy, runs_root / run_id)
        results[recipe_id] = result
        _print_run(console, result)

    console.title("\n3/4  Paired A/B against the locked recipe")
    comparisons_root = args.out / "comparisons"
    if "locked" in results:
        for recipe_id, result in results.items():
            if recipe_id == "locked":
                continue
            metric = "technical" if recipe_id == "overcooked" else "identity"
            comparison = compare(
                result, results["locked"], metric=metric, policy=suite_file.comparison_policy
            )
            save_comparison(comparison, comparisons_root)
            (comparisons_root / f"{comparison.comparison_id}.html").write_text(
                render_comparison_report(comparison, baseline=result, challenger=results["locked"]),
                encoding="utf-8",
            )
            _print_comparison(console, comparison)

    console.title("\n4/4  Done")
    console.write(f"  runs         {runs_root}")
    console.write(f"  comparisons  {comparisons_root}")
    console.write(f"  open         {runs_root / 'demo.locked' / 'report.html'}")
    console.muted("\n  `identitylock serve` opens the dashboard over these results.")
    return EXIT_OK


def cmd_report(args: argparse.Namespace) -> int:
    console = Console()
    result = load_run(args.run)
    policy = _load(args.suite).policy if args.suite else None
    target = args.output or (Path(args.run) / "report.html")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_run_report(result, policy=policy), encoding="utf-8")
    console.write(f"  {target}")
    return EXIT_OK


def cmd_runs(args: argparse.Namespace) -> int:
    console = Console()
    results = list_runs(args.out / "runs")
    if not results:
        console.write(f"  no runs under {args.out / 'runs'}")
        return EXIT_OK
    console.write(f"  {'run':<28}{'verdict':<9}{'identity':>9}{'accepted':>10}  label")
    for result in results:
        console.write(
            f"  {result.run_id:<28}{'pass' if result.verdict.passed else 'FAIL':<9}"
            f"{result.aggregates.identity_mean:>+9.3f}"
            f"{result.aggregates.n_accepted:>6}/{result.aggregates.n_total:<3}  {result.label}"
        )
    return EXIT_OK


def cmd_serve(args: argparse.Namespace) -> int:
    console = Console()
    try:
        import uvicorn

        from identitylock.api.app import create_app
    except ImportError:
        console.write(
            "  The dashboard needs the api extra. Install it with: pip install 'identity-lock[api]'"
        )
        return EXIT_ERROR

    console.title(f"Identity Lock dashboard on http://{args.host}:{args.port}")
    console.muted(f"  serving results from {args.out.resolve()}")
    uvicorn.run(create_app(args.out), host=args.host, port=args.port, log_level="warning")
    return EXIT_OK


# --------------------------------------------------------------------------- #
# Parser
# --------------------------------------------------------------------------- #


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="identitylock",
        description="Measure whether a generation pipeline keeps a character on-model.",
    )
    parser.add_argument("--version", action="version", version=f"identity-lock {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_common(target: argparse.ArgumentParser, *, suite: bool = True) -> None:
        if suite:
            target.add_argument(
                "--suite", type=Path, default=Path("suites/demo.yaml"), help="suite YAML file"
            )
        target.add_argument(
            "--out", type=Path, default=DEFAULT_WORKDIR, help="working directory for artefacts"
        )
        target.add_argument(
            "--embedder",
            default=DEFAULT_EMBEDDER,
            choices=registered(),
            help="identity descriptor backend",
        )
        target.add_argument(
            "--provider",
            default="synthetic",
            choices=("synthetic", "directory", "comfyui"),
            help="where frames come from",
        )
        target.add_argument("--images", type=Path, help="directory provider: folder of frames")
        target.add_argument("--comfyui", help="comfyui provider: base url, e.g. http://host:8188")
        target.add_argument("--workflow", type=Path, help="comfyui provider: API-format workflow")

    bootstrap = subparsers.add_parser("bootstrap", help="render the reference sets")
    add_common(bootstrap)
    bootstrap.add_argument("--count", type=int, help="frames per character")
    bootstrap.add_argument("--force", action="store_true", help="overwrite existing references")
    bootstrap.set_defaults(handler=cmd_bootstrap)

    calibrate = subparsers.add_parser(
        "calibrate", help="derive thresholds from a labelled validation set"
    )
    add_common(calibrate)
    calibrate.add_argument("--recipe", default="locked", help="recipe used for validation frames")
    calibrate.add_argument("--seeds", type=int, default=3, help="validation seeds per prompt")
    calibrate.add_argument("--far", type=float, default=0.02, help="target false-accept rate")
    calibrate.add_argument("--write", action="store_true", help="store thresholds in the suite")
    calibrate.add_argument("--json", action="store_true", help="machine-readable output")
    calibrate.set_defaults(handler=cmd_calibrate)

    run = subparsers.add_parser("run", help="generate and score one suite")
    add_common(run)
    run.add_argument("--recipe", required=True, help="recipe id from the suite file")
    run.add_argument("--run-id", help="fixed run id (default: suite.recipe.timestamp)")
    run.add_argument("--no-report", action="store_true", help="skip the HTML report")
    run.add_argument("--gate", action="store_true", help="exit 1 when the run fails its gates")
    run.set_defaults(handler=cmd_run)

    comparison = subparsers.add_parser("compare", help="paired A/B between two runs")
    comparison.add_argument("--baseline", type=Path, required=True, help="baseline run directory")
    comparison.add_argument(
        "--challenger", type=Path, required=True, help="challenger run directory"
    )
    comparison.add_argument(
        "--metric",
        default="identity",
        choices=("identity", "margin", "technical", "nearest_reference"),
    )
    comparison.add_argument("--suite", type=Path, help="suite file, for its comparison policy")
    comparison.add_argument("--out", type=Path, default=DEFAULT_WORKDIR)
    comparison.add_argument("--gate", action="store_true", help="exit 1 on a measured regression")
    comparison.set_defaults(handler=cmd_compare)

    demo = subparsers.add_parser("demo", help="bootstrap, run every recipe, compare, report")
    add_common(demo)
    demo.set_defaults(handler=cmd_demo)

    report = subparsers.add_parser("report", help="re-render the HTML report for a run")
    report.add_argument("--run", type=Path, required=True, help="run directory or run.json")
    report.add_argument("--suite", type=Path, help="suite file, so gates appear on the charts")
    report.add_argument("--output", type=Path, help="destination file")
    report.set_defaults(handler=cmd_report)

    runs = subparsers.add_parser("runs", help="list stored runs")
    runs.add_argument("--out", type=Path, default=DEFAULT_WORKDIR)
    runs.set_defaults(handler=cmd_runs)

    serve = subparsers.add_parser("serve", help="dashboard over the stored results")
    serve.add_argument("--out", type=Path, default=DEFAULT_WORKDIR)
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8420)
    serve.set_defaults(handler=cmd_serve)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    console = Console(sys.stderr)
    try:
        handler = args.handler
        result: int = handler(args)
        return result
    except (SuiteFileError, EvaluationError, ProviderError, ComparisonError, StoreError) as error:
        console.write(f"  {console.bad('error')} {error}")
        return EXIT_ERROR
    except KeyboardInterrupt:  # pragma: no cover - interactive
        console.write("  interrupted")
        return EXIT_ERROR


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
