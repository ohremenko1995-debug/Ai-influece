"""Command line.

    seedance rates --duration 5 --resolution 720p     what a clip costs, everywhere
    seedance draft "a prompt" --variants 3            cheap takes at 480p
    seedance final --pick 2                           promote one to 720p
    seedance spend                                    what has gone out today

`--dry-run` on the generating commands prints the exact HTTP request and the
cost it would incur, and sends nothing.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from seedance.config import Settings, load_settings
from seedance.ledger import BudgetExceededError, Ledger, open_ledger
from seedance.models import JobKind, JobRecord, JobSpec, Resolution
from seedance.pipeline import (
    PipelineError,
    draft_specs,
    final_spec,
    pick_draft,
    plan,
    run_drafts,
    run_final,
)
from seedance.pricing import PricingError, RateTable, load_rates
from seedance.providers import get_provider
from seedance.runner import Runner

app = typer.Typer(
    add_completion=False,
    help="Cost-aware gateway for Seedance 2.5.",
    no_args_is_help=True,
)
console = Console()


def _fail(message: str) -> typer.Exit:
    console.print(f"[red]{message}[/red]")
    return typer.Exit(code=1)


def _context() -> tuple[Settings, RateTable]:
    return load_settings(), load_rates()


def _runner(settings: Settings, rates: RateTable, ledger: Ledger, provider_name: str) -> Runner:
    return Runner(
        settings=settings,
        rates=rates,
        ledger=ledger,
        provider=get_provider(provider_name, settings),
        on_event=lambda message: console.print(f"[dim]{message}[/dim]"),
    )


def _report(jobs: list[JobRecord], title: str, *, wide: bool = False) -> None:
    """Render a batch of jobs.

    Narrow by default: after a `draft` or `final` the provider and kind are
    already on screen, and an 80-column terminal has no room to repeat them —
    squeezing them in truncates the status, which is the column that matters.
    """
    table = Table(title=title)
    table.add_column("#", width=3)
    table.add_column("job", no_wrap=True)
    if wide:
        table.add_column("kind")
        table.add_column("provider")
    table.add_column("seed", justify="right")
    table.add_column("res")
    table.add_column("status", no_wrap=True)
    table.add_column("billed", justify="right", no_wrap=True)
    table.add_column("output", overflow="fold")

    for index, job in enumerate(jobs, start=1):
        billed = f"${job.billed_usd:.3f}" + (" c" if job.cached else "")
        row = [str(index), job.id]
        if wide:
            row += [job.kind.value, job.provider]
        row += [
            str(job.spec.seed if job.spec.seed is not None else "-"),
            job.spec.resolution.value,
            job.status.value,
            billed,
            job.video_path or (job.error or ""),
        ]
        table.add_row(*row)

    console.print(table)
    total = sum(job.billed_usd for job in jobs)
    cached = sum(1 for job in jobs if job.cached)
    suffix = f", {cached} served from cache" if cached else ""
    console.print(f"[bold]batch total: ${total:.3f}[/bold]{suffix}")


# ---------------------------------------------------------------------------
# Prices
# ---------------------------------------------------------------------------
@app.command()
def rates(
    duration: Annotated[int, typer.Option(help="Clip length in seconds.")] = 5,
    resolution: Annotated[Resolution, typer.Option()] = Resolution.R720P,
    adapters_only: Annotated[
        bool, typer.Option(help="Only providers this tool can actually call.")
    ] = False,
) -> None:
    """Price one clip across every provider in the table."""
    _, rate_table = _context()
    spec = JobSpec(prompt="rate check", resolution=resolution, duration_s=duration)

    table = Table(title=f"Seedance 2.5 — {duration}s at {resolution.value}", show_lines=False)
    table.add_column("Provider")
    table.add_column("Per clip", justify="right")
    table.add_column("Per second", justify="right")
    table.add_column("Checked")
    table.add_column("Note", overflow="fold")

    for rate, estimate, reason in rate_table.compare(spec, adapters_only=adapters_only):
        if estimate is None:
            table.add_row(rate.label, "[dim]—[/dim]", "[dim]—[/dim]", rate.checked_at, reason or "")
            continue
        table.add_row(
            rate.label,
            f"${estimate.usd:.3f}",
            f"${estimate.usd / duration:.4f}",
            rate.checked_at,
            rate.notes,
        )

    console.print(table)
    console.print(
        "[dim]List prices as recorded in rates.toml. They move — re-read the console "
        "before a large run.[/dim]"
    )


@app.command()
def estimate(
    prompt: Annotated[str, typer.Argument()],
    provider: Annotated[str, typer.Option()] = "modelark",
    resolution: Annotated[Resolution, typer.Option()] = Resolution.R480P,
    duration: Annotated[int, typer.Option()] = 5,
    variants: Annotated[int, typer.Option(help="How many takes.")] = 1,
) -> None:
    """Cost a specific job without submitting it."""
    _, rate_table = _context()
    specs = draft_specs(
        prompt,
        variants=variants,
        resolution=resolution,
        duration_s=duration,
        seed_base=1,
    )
    try:
        run_plan = plan(rate_table, provider, specs)
    except PricingError as exc:
        raise _fail(str(exc)) from exc

    for index, (spec, cost) in enumerate(zip(run_plan.specs, run_plan.per_job, strict=True), 1):
        console.print(f"{index}. seed {spec.seed}: ${cost.usd:.4f}  [dim]{cost.detail}[/dim]")
    console.print(f"[bold]total ${run_plan.total_usd:.4f}[/bold] on {provider}")


# ---------------------------------------------------------------------------
# Generating
# ---------------------------------------------------------------------------
@app.command()
def draft(
    prompt: Annotated[str, typer.Argument()],
    variants: Annotated[int, typer.Option("--variants", "-n", help="Seeds to try.")] = 3,
    provider: Annotated[str | None, typer.Option()] = None,
    resolution: Annotated[Resolution | None, typer.Option()] = None,
    duration: Annotated[int, typer.Option()] = 5,
    seed_base: Annotated[int, typer.Option(help="First seed; the run uses N in sequence.")] = 1000,
    image: Annotated[str | None, typer.Option(help="First-frame image URL.")] = None,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Print, do not send.")] = False,
    force: Annotated[bool, typer.Option("--force", help="Ignore the budget cap.")] = False,
) -> None:
    """Generate cheap takes to choose from."""
    settings, rate_table = _context()
    provider_name = provider or settings.draft_provider
    specs = draft_specs(
        prompt,
        variants=variants,
        resolution=resolution or settings.draft_resolution,
        duration_s=duration,
        seed_base=seed_base,
        image_url=image,
    )

    try:
        run_plan = plan(rate_table, provider_name, specs)
    except PricingError as exc:
        raise _fail(str(exc)) from exc

    console.print(
        f"{len(specs)} takes on [bold]{provider_name}[/bold] "
        f"at {specs[0].resolution.value}: [bold]${run_plan.total_usd:.3f}[/bold]"
    )

    if dry_run:
        request = get_provider(provider_name, settings).prepare_submit(specs[0]).redacted()
        console.print("[dim]first request that would be sent:[/dim]")
        console.print_json(
            json.dumps(
                {
                    "method": request.method,
                    "url": request.url,
                    "headers": request.headers,
                    "json": request.json,
                }
            )
        )
        return

    with open_ledger(settings.db_path) as ledger:
        runner = _runner(settings, rate_table, ledger, provider_name)
        try:
            jobs = asyncio.run(run_drafts(runner, specs, force=force))
        except BudgetExceededError as exc:
            raise _fail(str(exc)) from exc

    _report(jobs, "drafts")


@app.command()
def final(
    run_id: Annotated[str | None, typer.Argument(help="Defaults to the latest draft run.")] = None,
    pick: Annotated[int | None, typer.Option("--pick", "-p", help="1-based draft number.")] = None,
    seed: Annotated[int | None, typer.Option(help="Promote the draft with this seed.")] = None,
    provider: Annotated[str | None, typer.Option()] = None,
    resolution: Annotated[Resolution | None, typer.Option()] = None,
    duration: Annotated[int | None, typer.Option(help="Override the draft's length.")] = None,
    force: Annotated[bool, typer.Option("--force")] = False,
) -> None:
    """Re-run one approved draft at final resolution, same seed."""
    settings, rate_table = _context()

    with open_ledger(settings.db_path) as ledger:
        target_run = run_id or ledger.latest_run_id(JobKind.DRAFT)
        if target_run is None:
            raise _fail("no draft run found — run `seedance draft` first")

        drafts = [job for job in ledger.by_run(target_run) if job.kind is JobKind.DRAFT]
        try:
            chosen = pick_draft(drafts, index=pick, seed=seed)
        except PipelineError as exc:
            raise _fail(str(exc)) from exc

        spec = final_spec(
            chosen,
            resolution=resolution or settings.final_resolution,
            duration_s=duration,
        )
        provider_name = provider or settings.final_provider
        try:
            cost = rate_table.estimate(provider_name, spec)
        except PricingError as exc:
            raise _fail(str(exc)) from exc

        console.print(
            f"promoting seed {spec.seed} to {spec.resolution.value} on "
            f"[bold]{provider_name}[/bold]: [bold]${cost.usd:.3f}[/bold]"
        )

        runner = _runner(settings, rate_table, ledger, provider_name)
        try:
            job = asyncio.run(run_final(runner, spec, run_id=target_run, force=force))
        except BudgetExceededError as exc:
            raise _fail(str(exc)) from exc

    _report([job], "final")


# ---------------------------------------------------------------------------
# Books
# ---------------------------------------------------------------------------
@app.command()
def jobs(limit: Annotated[int, typer.Option()] = 20) -> None:
    """Recent jobs."""
    settings, _ = _context()
    with open_ledger(settings.db_path) as ledger:
        _report(ledger.recent(limit), f"last {limit} jobs", wide=True)


@app.command()
def run(run_id: Annotated[str, typer.Argument()]) -> None:
    """Everything in one run."""
    settings, _ = _context()
    with open_ledger(settings.db_path) as ledger:
        _report(ledger.by_run(run_id), f"run {run_id}", wide=True)


@app.command()
def spend() -> None:
    """Committed spend against the caps."""
    settings, _ = _context()
    with open_ledger(settings.db_path) as ledger:
        for window, spent, fallback in (
            ("daily", ledger.today_spend(), settings.daily_budget_usd),
            ("monthly", ledger.month_spend(), settings.monthly_budget_usd),
        ):
            cap = ledger.cap(window, fallback)
            limit = f"of ${cap:.2f}" if cap > 0 else "[dim](no cap set)[/dim]"
            console.print(f"{window:8} ${spent:.2f} {limit}")


@app.command()
def budget(
    daily: Annotated[float | None, typer.Option(help="USD per day, 0 to clear.")] = None,
    monthly: Annotated[float | None, typer.Option(help="USD per month, 0 to clear.")] = None,
) -> None:
    """Set the spend caps that block submissions."""
    settings, _ = _context()
    with open_ledger(settings.db_path) as ledger:
        if daily is not None:
            ledger.set_cap("daily", daily)
        if monthly is not None:
            ledger.set_cap("monthly", monthly)
        console.print(
            f"daily ${ledger.cap('daily', settings.daily_budget_usd):.2f}, "
            f"monthly ${ledger.cap('monthly', settings.monthly_budget_usd):.2f}"
        )


@app.command()
def providers() -> None:
    """Which adapters are configured and callable."""
    settings, rate_table = _context()
    table = Table(title="adapters")
    table.add_column("provider")
    table.add_column("credentials")
    table.add_column("priced for", overflow="fold")

    for name in ("modelark", "replicate", "wavespeed", "wavespeed_turbo", "fake"):
        adapter = get_provider(name, settings)
        rate = rate_table.providers.get(adapter.rate_key)
        priced = ", ".join(sorted(rate.usd_per_second or {})) if rate else "?"
        if rate and rate.billing == "token":
            priced = "all resolutions (token formula)"
        table.add_row(
            name,
            "[green]set[/green]" if adapter.available else "[yellow]missing[/yellow]",
            priced,
        )
    console.print(table)
    console.print(f"[dim]ledger: {Path(settings.db_path).resolve()}[/dim]")


if __name__ == "__main__":  # pragma: no cover
    app()
