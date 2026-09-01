#!/usr/bin/env python3
"""Render the README's charts from real run data.

The charts in the README are not screenshots and not hand-drawn: this script reads
`var/runs/*/run.json` and the calibration JSON produced by `identitylock calibrate
--json`, and emits SVG. `make charts` regenerates them, so a number in the README
that stops matching the code is a diff, not a discovery.

Two files per chart, light and dark. The README pairs them with `<picture>` so
GitHub serves whichever matches the reader's theme. The dark steps are chosen for
the dark surface — not an automatic inversion of the light ones.

Charts are static images here: no hover, no tooltip. Everything a tooltip would
have carried is therefore either directly labelled on the mark or present in the
markdown table beside the figure.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from html import escape
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from identitylock.domain.models import Comparison, RunResult
from identitylock.evaluation.store import list_comparisons, list_runs

FONT = "system-ui, -apple-system, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif"

DEMO_ORDER = ("locked", "baseline", "drifting", "overcooked")


@dataclass(frozen=True, slots=True)
class Theme:
    """One selected palette instance. Dark is re-stepped, never flipped."""

    name: str
    surface: str
    ink: str
    ink_secondary: str
    muted: str
    grid: str
    axis: str
    series_1: str
    series_2: str
    good: str
    warning: str
    critical: str


# Surfaces are GitHub's own canvas colours so the figures sit flush in the README.
# Both palettes were run through the data-viz validator against those surfaces:
# all six checks pass in both modes.
LIGHT = Theme(
    name="light",
    surface="#ffffff",
    ink="#0b0b0b",
    ink_secondary="#52514e",
    muted="#898781",
    grid="#e1e0d9",
    axis="#c3c2b7",
    series_1="#2a78d6",
    series_2="#eb6834",
    good="#0ca30c",
    warning="#fab219",
    critical="#d03b3b",
)

DARK = Theme(
    name="dark",
    surface="#0d1117",
    ink="#ffffff",
    ink_secondary="#c3c2b7",
    muted="#898781",
    grid="#2c2c2a",
    axis="#383835",
    series_1="#3987e5",
    series_2="#d95926",
    good="#0ca30c",
    warning="#fab219",
    critical="#d03b3b",
)


# --------------------------------------------------------------------------- #
# SVG primitives
# --------------------------------------------------------------------------- #


def svg(width: float, height: float, body: str, theme: Theme, label: str) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width:.0f}" height="{height:.0f}" '
        f'viewBox="0 0 {width:.0f} {height:.0f}" role="img" aria-label="{escape(label)}" '
        f'font-family="{FONT}">'
        f'<rect width="{width:.0f}" height="{height:.0f}" fill="{theme.surface}"/>'
        f"{body}</svg>\n"
    )


def text(
    x: float,
    y: float,
    content: str,
    *,
    fill: str,
    size: float = 11,
    anchor: str = "start",
    weight: str = "400",
    tabular: bool = False,
) -> str:
    numeric = ' font-variant-numeric="tabular-nums"' if tabular else ""
    return (
        f'<text x="{x:.1f}" y="{y:.1f}" fill="{fill}" font-size="{size:.0f}" '
        f'text-anchor="{anchor}" font-weight="{weight}"{numeric}>{escape(content)}</text>'
    )


def line(
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    *,
    stroke: str,
    width: float = 1.0,
    dash: str = "",
    cap: str = "butt",
) -> str:
    dasharray = f' stroke-dasharray="{dash}"' if dash else ""
    return (
        f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
        f'stroke="{stroke}" stroke-width="{width}" stroke-linecap="{cap}"{dasharray}/>'
    )


def dot(x: float, y: float, *, fill: str, ring: str, radius: float = 5.0) -> str:
    """A marker with the 2px surface ring that keeps it legible over other marks."""
    return (
        f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{radius:.1f}" fill="{fill}" '
        f'stroke="{ring}" stroke-width="2"/>'
    )


def column(
    x: float, y: float, w: float, h: float, *, fill: str, radius: float = 4.0, down: bool = False
) -> str:
    """A column with a rounded data-end and a square baseline."""
    if h <= 0.5:
        return ""
    r = min(radius, w / 2, h)
    if down:
        return (
            f'<path d="M{x:.1f},{y:.1f} h{w:.1f} v{h - r:.1f} '
            f"a{r:.1f},{r:.1f} 0 0 1 -{r:.1f},{r:.1f} "
            f'h-{w - 2 * r:.1f} a{r:.1f},{r:.1f} 0 0 1 -{r:.1f},-{r:.1f} z" fill="{fill}"/>'
        )
    return (
        f'<path d="M{x:.1f},{y + h:.1f} v-{h - r:.1f} a{r:.1f},{r:.1f} 0 0 1 {r:.1f},-{r:.1f} '
        f'h{w - 2 * r:.1f} a{r:.1f},{r:.1f} 0 0 1 {r:.1f},{r:.1f} v{h - r:.1f} z" fill="{fill}"/>'
    )


def nice_ticks(low: float, high: float, count: int = 5) -> list[float]:
    if high <= low:
        return [low]
    raw = (high - low) / max(count - 1, 1)
    magnitude = 10.0 ** _floor_log10(raw)
    step = next((s * magnitude for s in (1, 2, 2.5, 5, 10) if s * magnitude >= raw), magnitude)
    ticks: list[float] = []
    value = _ceil_to(low, step)
    while value <= high + step * 1e-9:
        ticks.append(round(value, 10))
        value += step
    return ticks or [low, high]


def _floor_log10(value: float) -> int:
    exponent = 0
    magnitude = abs(value) or 1.0
    while magnitude < 1.0:
        magnitude *= 10.0
        exponent -= 1
    while magnitude >= 10.0:
        magnitude /= 10.0
        exponent += 1
    return exponent


def _ceil_to(value: float, step: float) -> float:
    return (
        step * (int(value / step) + (1 if value % step else 0))
        if value > 0
        else step * int(value / step)
    )


def fmt(value: float, digits: int = 2) -> str:
    return f"{value:.{digits}f}".rstrip("0").rstrip(".") or "0"


def signed(value: float, digits: int = 3) -> str:
    return f"{value:+.{digits}f}"


@dataclass(frozen=True, slots=True)
class Scale:
    lo: float
    hi: float
    px_lo: float
    px_hi: float

    def __call__(self, value: float) -> float:
        span = self.hi - self.lo or 1.0
        return self.px_lo + (value - self.lo) / span * (self.px_hi - self.px_lo)


def x_axis(
    scale: Scale, top: float, bottom: float, theme: Theme, label: str, *, digits: int = 2
) -> str:
    parts = [line(scale.px_lo, bottom, scale.px_hi, bottom, stroke=theme.axis)]
    for tick in nice_ticks(scale.lo, scale.hi):
        if not scale.lo <= tick <= scale.hi:
            continue
        x = scale(tick)
        parts.append(line(x, top, x, bottom, stroke=theme.grid))
        parts.append(
            text(
                x,
                bottom + 15,
                fmt(tick, digits),
                fill=theme.muted,
                size=10,
                anchor="middle",
                tabular=True,
            )
        )
    parts.append(
        text(
            (scale.px_lo + scale.px_hi) / 2,
            bottom + 32,
            label,
            fill=theme.muted,
            size=11,
            anchor="middle",
        )
    )
    return "".join(parts)


def legend(x: float, y: float, entries: list[tuple[str, str]], theme: Theme) -> str:
    """Swatch plus text-token label — identity is never colour alone."""
    parts: list[str] = []
    offset = x
    for colour, name in entries:
        parts.append(
            f'<rect x="{offset:.1f}" y="{y - 7:.1f}" width="10" height="10" '
            f'rx="2" fill="{colour}"/>'
        )
        parts.append(text(offset + 15, y + 2, name, fill=theme.ink_secondary, size=11))
        offset += 15 + 7.0 * len(name) + 22
    return "".join(parts)


def caption(x: float, y: float, content: str, theme: Theme) -> str:
    return text(x, y, content, fill=theme.muted, size=11)


def heading(x: float, y: float, content: str, theme: Theme) -> str:
    return text(x, y, content, fill=theme.ink, size=13, weight="600")


# --------------------------------------------------------------------------- #
# Charts
# --------------------------------------------------------------------------- #

WIDTH = 880.0


def chart_verdicts(runs: list[RunResult], threshold: float, theme: Theme) -> str:
    """Identity per recipe: full range, 95% interval, mean — coloured by verdict.

    One measure across four categories, so no categorical palette: the colour
    carries pass/fail state, and every row is also labelled in words.
    """
    left, right = 168.0, 92.0
    row_height = 46.0
    top = 92.0
    height = top + row_height * len(runs) + 66.0
    scale = Scale(
        min(min(r.aggregates.identity_min for r in runs), threshold) - 0.06,
        max(r.aggregates.identity_max for r in runs) + 0.06,
        left,
        WIDTH - right,
    )
    bottom = top + row_height * len(runs) - 12.0

    parts = [
        heading(left - 148, 28, "Identity per recipe, with the batch it came from", theme),
        caption(
            left - 148,
            46,
            "dot = mean · bar = 95% bootstrap CI · line = full range of the 24 takes",
            theme,
        ),
        x_axis(scale, top - 20, bottom, theme, "identity similarity (cosine, cohort-centred)"),
    ]

    gate_x = scale(threshold)
    parts.append(
        line(gate_x, top - 20, gate_x, bottom, stroke=theme.critical, width=1.4, dash="5 4")
    )
    parts.append(
        text(
            gate_x,
            top - 28,
            f"accept ≥ {fmt(threshold, 3)}",
            fill=theme.critical,
            size=10,
            anchor="middle",
            tabular=True,
        )
    )

    for index, run in enumerate(runs):
        y = top + row_height * index + 6
        aggregates = run.aggregates
        colour = theme.good if run.verdict.passed else theme.critical
        mark = "✓ pass" if run.verdict.passed else "✗ fail"
        name = run.suite.recipe.id

        parts.append(text(left - 148, y + 4, name, fill=theme.ink, size=12, weight="600"))
        parts.append(text(left - 148, y + 19, mark, fill=theme.ink_secondary, size=10.5))
        parts.append(
            text(
                left - 12,
                y + 4,
                f"{aggregates.n_accepted}/{aggregates.n_total}",
                fill=theme.muted,
                size=10.5,
                anchor="end",
                tabular=True,
            )
        )
        parts.append(text(left - 12, y + 18, "accepted", fill=theme.muted, size=9.5, anchor="end"))

        parts.append(
            line(
                scale(aggregates.identity_min),
                y,
                scale(aggregates.identity_max),
                y,
                stroke=theme.axis,
                width=1.5,
                cap="round",
            )
        )
        ci_width = scale(aggregates.identity_ci_high) - scale(aggregates.identity_ci_low)
        parts.append(
            f'<rect x="{scale(aggregates.identity_ci_low):.1f}" y="{y - 3:.1f}" '
            f'width="{max(ci_width, 2):.1f}" '
            f'height="6" rx="3" fill="{colour}"/>'
        )
        parts.append(dot(scale(aggregates.identity_mean), y, fill=colour, ring=theme.surface))
        parts.append(
            text(
                WIDTH - right + 12,
                y + 4,
                signed(aggregates.identity_mean),
                fill=theme.ink,
                size=11.5,
                tabular=True,
            )
        )

    parts.append(
        legend(
            left - 148,
            height - 14,
            [(theme.good, "passed every gate"), (theme.critical, "failed a gate")],
            theme,
        )
    )
    return svg(
        WIDTH,
        height,
        "".join(parts),
        theme,
        "identity similarity per recipe with confidence intervals",
    )


def chart_drift(locked: RunResult, drifting: RunResult, threshold: float, theme: Theme) -> str:
    """Identity against position in the batch for two recipes, with fitted trends."""
    left, right, top = 58.0, 128.0, 74.0
    height = 320.0
    bottom = height - 58.0
    series = [(locked, theme.series_1), (drifting, theme.series_2)]
    values = [item.metrics.identity_similarity for run, _ in series for item in run.candidates]
    scale_y = Scale(min(min(values), threshold) - 0.05, max(values) + 0.05, bottom, top)
    count = len(locked.candidates)
    scale_x = Scale(0, count - 1, left, WIDTH - right)

    parts = [
        heading(left - 44, 26, "Identity across the batch — the drift gate's evidence", theme),
        caption(
            left - 44,
            44,
            "prompts are interleaved, so a slope is degradation over the batch, "
            "not the prompt list",
            theme,
        ),
        caption(
            left - 44,
            60,
            "straight lines are the fitted trend after prompt effects are removed",
            theme,
        ),
    ]

    parts.append(line(left, bottom, WIDTH - right, bottom, stroke=theme.axis))
    for tick in nice_ticks(scale_y.lo, scale_y.hi):
        if not scale_y.lo <= tick <= scale_y.hi:
            continue
        y = scale_y(tick)
        parts.append(line(left, y, WIDTH - right, y, stroke=theme.grid))
        parts.append(
            text(
                left - 8, y + 3.5, fmt(tick), fill=theme.muted, size=10, anchor="end", tabular=True
            )
        )
    for tick in (0, 5, 10, 15, 20):
        parts.append(
            text(
                scale_x(tick),
                bottom + 16,
                str(tick),
                fill=theme.muted,
                size=10,
                anchor="middle",
                tabular=True,
            )
        )
    parts.append(
        text(
            (left + WIDTH - right) / 2,
            bottom + 33,
            "position in batch",
            fill=theme.muted,
            size=11,
            anchor="middle",
        )
    )
    parts.append(
        text(
            14,
            (top + bottom) / 2,
            "identity",
            fill=theme.muted,
            size=11,
            anchor="middle",
        ).replace("<text ", f'<text transform="rotate(-90 14 {(top + bottom) / 2:.1f})" ')
    )

    gate_y = scale_y(threshold)
    parts.append(
        line(left, gate_y, WIDTH - right, gate_y, stroke=theme.critical, width=1.4, dash="5 4")
    )
    parts.append(
        text(
            left + 4,
            gate_y - 7,
            f"accept ≥ {fmt(threshold, 3)}",
            fill=theme.critical,
            size=10,
            tabular=True,
        )
    )

    for run, colour in series:
        points = [item.metrics.identity_similarity for item in run.candidates]
        mean = sum(points) / len(points)
        centre = (len(points) - 1) / 2
        slope = run.aggregates.drift_slope / 10.0
        y_start = scale_y(mean + slope * (0 - centre))
        y_end = scale_y(mean + slope * (len(points) - 1 - centre))
        parts.append(
            line(
                scale_x(0),
                y_start,
                scale_x(len(points) - 1),
                y_end,
                stroke=colour,
                width=2,
                cap="round",
            )
        )
        for index, value in enumerate(points):
            parts.append(
                dot(scale_x(index), scale_y(value), fill=colour, ring=theme.surface, radius=4.0)
            )
        parts.append(
            text(
                WIDTH - right + 10,
                y_end + 4,
                f"{run.suite.recipe.id}",
                fill=theme.ink,
                size=11.5,
                weight="600",
            )
        )
        parts.append(
            text(
                WIDTH - right + 10,
                y_end + 19,
                f"{signed(run.aggregates.drift_slope, 4)}/10",
                fill=theme.ink_secondary,
                size=10.5,
                tabular=True,
            )
        )
        parts.append(
            text(
                WIDTH - right + 10,
                y_end + 32,
                f"p={fmt(run.aggregates.drift_p_value, 3)}",
                fill=theme.muted,
                size=10.5,
                tabular=True,
            )
        )

    parts.append(
        legend(
            left - 44, height - 12, [(colour, run.suite.recipe.id) for run, colour in series], theme
        )
    )
    return svg(
        WIDTH,
        height,
        "".join(parts),
        theme,
        "identity against position in the batch for two recipes",
    )


def chart_verification(calibration: dict[str, Any], theme: Theme) -> str:
    """Genuine and impostor score distributions, mirrored about the threshold axis."""
    genuine = list(calibration["scores"]["genuine"])
    impostor = list(calibration["scores"]["impostor"])
    threshold = float(calibration["policy"]["identity_min"])

    left, right, top = 58.0, 34.0, 116.0
    height = 376.0
    bottom = height - 58.0
    midline = (top + bottom) / 2

    low = min(min(genuine), min(impostor), threshold) - 0.05
    high = max(max(genuine), max(impostor), threshold) + 0.05
    bins = 30
    edges = [low + (high - low) * i / bins for i in range(bins + 1)]

    def histogram(values: list[float]) -> list[int]:
        counts = [0] * bins
        for value in values:
            slot = min(bins - 1, max(0, int((value - low) / (high - low) * bins)))
            counts[slot] += 1
        return counts

    genuine_counts = histogram(genuine)
    impostor_counts = histogram(impostor)
    # Each side is normalised to its own population. There are three impostor
    # scores per genuine one (one per other character in the cohort), so plotting
    # raw counts would make the impostor mass look three times as important as it is.
    genuine_peak = max(genuine_counts) or 1
    impostor_peak = max(impostor_counts) or 1
    scale_x = Scale(low, high, left, WIDTH - right)
    half = midline - top - 18

    parts = [
        heading(left - 44, 26, "Where the threshold comes from", theme),
        caption(
            left - 44,
            44,
            "every validation frame scored against its own character (up) "
            "and against every other one (down)",
            theme,
        ),
        caption(
            left - 44,
            60,
            f"AUC {calibration['auc']:.4f} · EER {calibration['eer'] * 100:.2f}% · "
            f"operating point FAR {calibration['achieved_far'] * 100:.2f}% "
            f"/ FRR {calibration['frr'] * 100:.2f}%",
            theme,
        ),
    ]

    for tick in nice_ticks(low, high):
        if not low <= tick <= high:
            continue
        x = scale_x(tick)
        parts.append(line(x, top, x, bottom, stroke=theme.grid))
        parts.append(
            text(
                x, bottom + 16, fmt(tick), fill=theme.muted, size=10, anchor="middle", tabular=True
            )
        )
    parts.append(
        text(
            (left + WIDTH - right) / 2,
            bottom + 33,
            "identity similarity",
            fill=theme.muted,
            size=11,
            anchor="middle",
        )
    )

    slot_width = scale_x(edges[1]) - scale_x(edges[0])
    bar_width = max(slot_width - 2.0, 2.0)
    for index in range(bins):
        x = scale_x(edges[index]) + 1.0
        if genuine_counts[index]:
            h = genuine_counts[index] / genuine_peak * half
            parts.append(column(x, midline - h - 1, bar_width, h, fill=theme.series_1))
        if impostor_counts[index]:
            h = impostor_counts[index] / impostor_peak * half
            parts.append(column(x, midline + 1, bar_width, h, fill=theme.series_2, down=True))

    parts.append(line(left, midline, WIDTH - right, midline, stroke=theme.axis))
    gate_x = scale_x(threshold)
    parts.append(line(gate_x, top, gate_x, bottom, stroke=theme.critical, width=1.4, dash="5 4"))
    # Above the plot band, not inside it: an annotation that lands on a bar is
    # unreadable however carefully it is nudged.
    parts.append(
        text(
            gate_x,
            top - 26,
            f"threshold {fmt(threshold, 4)}",
            fill=theme.critical,
            size=10.5,
            anchor="middle",
            tabular=True,
        )
    )
    parts.append(
        text(
            gate_x, top - 12, "chosen at FAR \u2264 2%", fill=theme.muted, size=10, anchor="middle"
        )
    )
    parts.append(line(gate_x, top - 8, gate_x, top, stroke=theme.critical, width=1.4, dash="5 4"))

    parts.append(
        text(
            left,
            midline - half - 8,
            f"genuine — {len(genuine)} frames, tallest bar {genuine_peak}",
            fill=theme.ink_secondary,
            size=10.5,
        )
    )
    parts.append(
        text(
            left,
            midline + half + 16,
            f"impostor — {len(impostor)} scores, tallest bar {impostor_peak}",
            fill=theme.ink_secondary,
            size=10.5,
        )
    )
    parts.append(
        text(
            WIDTH - right,
            midline - half - 8,
            "each side scaled to its own peak",
            fill=theme.muted,
            size=10,
            anchor="end",
        )
    )
    parts.append(
        legend(
            left - 44,
            height - 12,
            [(theme.series_1, "same character"), (theme.series_2, "other characters")],
            theme,
        )
    )
    return svg(
        WIDTH, height, "".join(parts), theme, "genuine and impostor identity score distributions"
    )


def chart_forest(comparisons: list[Comparison], theme: Theme) -> str:
    """Every A/B as a mean difference with its interval — the CI is the arbiter."""
    left, right = 296.0, 118.0
    row_height = 46.0
    top = 78.0
    height = top + row_height * len(comparisons) + 62.0
    bottom = top + row_height * len(comparisons) - 12.0
    span = max(max(abs(c.ci_low), abs(c.ci_high)) for c in comparisons) * 1.15
    scale = Scale(-span, span, left, WIDTH - right)

    colours = {
        "improvement": theme.good,
        "regression": theme.critical,
        "inconclusive": theme.warning,
    }
    marks = {
        "improvement": "✓ improvement",
        "regression": "✗ regression",
        "inconclusive": "— inconclusive",
    }

    parts = [
        heading(left - 276, 28, "Every A/B, as a mean difference with its 95% interval", theme),
        caption(
            left - 276,
            46,
            "paired cells: same prompt, same seed, same references — only the recipe differs",
            theme,
        ),
        # A typographic minus, not a hyphen: this is a subtraction on an axis label.
        x_axis(scale, top - 16, bottom, theme, "challenger \u2212 baseline", digits=2),
    ]
    zero = scale(0.0)
    parts.append(line(zero, top - 16, zero, bottom, stroke=theme.axis, width=1.4))

    for index, comparison in enumerate(comparisons):
        y = top + row_height * index + 6
        colour = colours[comparison.verdict.outcome]
        baseline = comparison.baseline_run_id.split(".")[-1]
        parts.append(
            text(left - 276, y + 1, f"locked vs {baseline}", fill=theme.ink, size=12, weight="600")
        )
        parts.append(
            text(
                left - 276,
                y + 16,
                f"on {comparison.metric} · win {comparison.win_rate:.0%} · n={comparison.n_pairs}",
                fill=theme.muted,
                size=10,
            )
        )
        parts.append(
            text(
                left - 22,
                y + 4,
                marks[comparison.verdict.outcome],
                fill=theme.ink_secondary,
                size=10.5,
                anchor="end",
            )
        )

        parts.append(
            line(
                scale(comparison.ci_low),
                y,
                scale(comparison.ci_high),
                y,
                stroke=colour,
                width=6,
                cap="round",
            )
        )
        parts.append(dot(scale(comparison.mean_delta), y, fill=colour, ring=theme.surface))
        parts.append(
            text(
                WIDTH - right + 12,
                y + 4,
                f"{signed(comparison.mean_delta, 4)}",
                fill=theme.ink,
                size=11.5,
                tabular=True,
            )
        )

    parts.append(
        legend(
            left - 276,
            height - 14,
            [(theme.good, "interval clears zero"), (theme.warning, "interval straddles zero")],
            theme,
        )
    )
    return svg(
        WIDTH,
        height,
        "".join(parts),
        theme,
        "mean difference and confidence interval for every comparison",
    )


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #


def candidate_threshold(runs: Sequence[RunResult]) -> float:
    """The per-candidate identity gate these runs were judged under.

    Read straight off the manifest — every run carries the policy it was gated
    with. This used to be reverse-engineered from which frames were rejected,
    which was a guess, and disagreed with the report whenever nothing had been
    rejected for identity.
    """
    thresholds = {run.manifest.policy.identity_min for run in runs}
    if len(thresholds) > 1:
        joined = ", ".join(f"{value:.4f}" for value in sorted(thresholds))
        raise SystemExit(
            f"the runs were judged under different identity thresholds ({joined}); "
            "one chart cannot draw one gate line for them. Re-run them under one policy."
        )
    return next(iter(thresholds))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=Path, default=Path("var/runs"))
    parser.add_argument("--comparisons", type=Path, default=Path("var/comparisons"))
    parser.add_argument("--calibration", type=Path, default=Path("var/calibration.json"))
    parser.add_argument("--out", type=Path, default=Path("docs/assets"))
    args = parser.parse_args(argv)

    runs = {run.suite.recipe.id: run for run in list_runs(args.runs)}
    order = [name for name in DEMO_ORDER if name in runs]
    if not order:
        parser.error(f"no runs under {args.runs} — run `make demo` first")
    ordered = [runs[name] for name in order]

    # Every figure below is *about* the locked recipe: it is the reference the
    # others are compared against. Without it the charts would be mislabelled
    # rather than merely incomplete, so say so instead of raising a KeyError.
    if "locked" not in runs:
        parser.error(
            f"no `locked` run under {args.runs} — the figures compare the other "
            "recipes against it. Run `make demo`, or `identitylock run --recipe locked`."
        )
    drifting = runs.get("drifting", ordered[-1])

    comparisons = list_comparisons(args.comparisons)
    rank = {"identity": 0, "technical": 1}
    comparisons.sort(key=lambda c: (rank.get(c.metric, 9), c.baseline_run_id))

    calibration = json.loads(args.calibration.read_text(encoding="utf-8"))
    threshold = candidate_threshold(ordered)

    args.out.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    skipped: list[str] = []
    for theme in (LIGHT, DARK):
        figures = {
            "verdicts": chart_verdicts(ordered, threshold, theme),
            "drift": chart_drift(runs["locked"], drifting, threshold, theme),
            "verification": chart_verification(calibration, theme),
            # An empty comparison set is a normal state (nothing compared yet), not
            # an error — but it must not half-write the figure set either.
            "comparisons": chart_forest(comparisons, theme) if comparisons else "",
        }
        for name, markup in figures.items():
            if not markup:
                skipped.append(f"{name}-{theme.name}.svg")
                continue
            path = args.out / f"{name}-{theme.name}.svg"
            path.write_text(markup, encoding="utf-8")
            written.append(path)

    for path in written:
        print(f"  {path}  {path.stat().st_size / 1024:.1f} kB")
    for name in skipped:
        print(f"  skipped {name} — nothing to plot")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
