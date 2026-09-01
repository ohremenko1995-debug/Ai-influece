"""Inline SVG charts.

Hand-written rather than pulled from a plotting library, for one reason: the
report has to be a single file that still works when it is emailed, attached to a
ticket or opened from a USB stick two years from now. That rules out a CDN script
tag, and rendering to PNG would lose the crispness and the theme awareness.

Every chart takes plain numbers and returns an SVG string. They know nothing about
runs, candidates or policies — that is the report's job.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from html import escape


@dataclass(frozen=True, slots=True)
class Box:
    """Plot area in SVG user units, excluding the axis gutters."""

    width: float
    height: float
    left: float = 46.0
    right: float = 12.0
    top: float = 12.0
    bottom: float = 36.0

    @property
    def inner_width(self) -> float:
        return self.width - self.left - self.right

    @property
    def inner_height(self) -> float:
        return self.height - self.top - self.bottom


def _nice_ticks(low: float, high: float, count: int = 5) -> list[float]:
    """Round tick positions covering [low, high], in the 1/2/5 x 10^n family."""
    if high <= low:
        return [low]
    raw = (high - low) / max(count - 1, 1)
    magnitude = 10.0 ** (len(f"{int(abs(raw)):d}") - 1) if abs(raw) >= 1 else 1.0
    while magnitude > abs(raw):
        magnitude /= 10.0
    for step in (1.0, 2.0, 2.5, 5.0, 10.0):
        candidate = step * magnitude
        if candidate >= raw:
            break
    start = candidate * (low // candidate)
    ticks: list[float] = []
    value = start
    while value <= high + candidate * 0.5:
        if value >= low - candidate * 0.5:
            ticks.append(round(value, 10))
        value += candidate
    return ticks or [low, high]


def _fmt(value: float) -> str:
    if abs(value) >= 100:
        return f"{value:.0f}"
    if abs(value) >= 1:
        return f"{value:.2f}".rstrip("0").rstrip(".")
    return f"{value:.3f}".rstrip("0").rstrip(".") or "0"


class _Axes:
    """Maps data coordinates to SVG coordinates and draws the frame."""

    def __init__(
        self, box: Box, x_range: tuple[float, float], y_range: tuple[float, float]
    ) -> None:
        self.box = box
        self.x0, self.x1 = x_range if x_range[1] > x_range[0] else (x_range[0], x_range[0] + 1.0)
        self.y0, self.y1 = y_range if y_range[1] > y_range[0] else (y_range[0], y_range[0] + 1.0)

    def sx(self, value: float) -> float:
        span = self.x1 - self.x0
        return self.box.left + (value - self.x0) / span * self.box.inner_width

    def sy(self, value: float) -> float:
        span = self.y1 - self.y0
        return (
            self.box.top + self.box.inner_height - (value - self.y0) / span * self.box.inner_height
        )

    def frame(self, *, x_label: str, y_label: str, x_ticks: Sequence[float] | None = None) -> str:
        parts: list[str] = []
        for tick in _nice_ticks(self.y0, self.y1):
            if not self.y0 - 1e-9 <= tick <= self.y1 + 1e-9:
                continue  # a nice round tick can fall outside the data range
            y = self.sy(tick)
            parts.append(
                f'<line class="il-grid" x1="{self.box.left:.1f}" y1="{y:.1f}" '
                f'x2="{self.box.width - self.box.right:.1f}" y2="{y:.1f}"/>'
            )
            parts.append(
                f'<text class="il-tick" x="{self.box.left - 6:.1f}" y="{y + 3.5:.1f}" '
                f'text-anchor="end">{_fmt(tick)}</text>'
            )
        for tick in x_ticks if x_ticks is not None else _nice_ticks(self.x0, self.x1):
            if not self.x0 - 1e-9 <= tick <= self.x1 + 1e-9:
                continue
            x = self.sx(tick)
            parts.append(
                f'<text class="il-tick" x="{x:.1f}" y="{self.box.height - 12:.1f}" '
                f'text-anchor="middle">{_fmt(tick)}</text>'
            )
        parts.append(
            f'<text class="il-axis" x="{self.box.width / 2:.1f}" y="{self.box.height - 1:.1f}" '
            f'text-anchor="middle">{escape(x_label)}</text>'
        )
        parts.append(
            f'<text class="il-axis" '
            f'transform="translate(10,{self.box.height / 2:.1f}) rotate(-90)" '
            f'text-anchor="middle">{escape(y_label)}</text>'
        )
        return "".join(parts)


def _svg(box: Box, body: str, title: str) -> str:
    return (
        f'<svg class="il-chart" viewBox="0 0 {box.width:.0f} {box.height:.0f}" '
        f'role="img" aria-label="{escape(title)}" preserveAspectRatio="xMidYMid meet">{body}</svg>'
    )


def drift_chart(
    values: Sequence[float],
    *,
    accepted: Sequence[bool],
    threshold: float,
    slope_per_10: float,
    width: float = 620.0,
    height: float = 230.0,
) -> str:
    """Identity against position in the batch, with the gate and the fitted trend."""
    if not values:
        return ""
    box = Box(width=width, height=height)
    low = min(min(values), threshold) - 0.05
    high = max(max(values), threshold) + 0.05
    axes = _Axes(box, (0.0, float(len(values) - 1 or 1)), (low, high))

    parts = [axes.frame(x_label="position in batch", y_label="identity")]
    y = axes.sy(threshold)
    label = f"accept \u2265 {_fmt(threshold)}"
    # The dashed line stops short of its own label so the two never overlap.
    label_width = 7.0 * len(label)
    parts.append(
        f'<line class="il-threshold" x1="{box.left:.1f}" y1="{y:.1f}" '
        f'x2="{width - box.right - label_width - 6:.1f}" y2="{y:.1f}"/>'
    )
    parts.append(
        f'<text class="il-tick il-threshold-label" x="{width - box.right:.1f}" '
        f'y="{y + 3.5:.1f}" text-anchor="end">{escape(label)}</text>'
    )

    mean_value = sum(values) / len(values)
    centre = (len(values) - 1) / 2.0
    slope = slope_per_10 / 10.0
    start = mean_value + slope * (0 - centre)
    end = mean_value + slope * (len(values) - 1 - centre)
    parts.append(
        f'<line class="il-trend" x1="{axes.sx(0):.1f}" y1="{axes.sy(start):.1f}" '
        f'x2="{axes.sx(len(values) - 1):.1f}" y2="{axes.sy(end):.1f}"/>'
    )

    for index, value in enumerate(values):
        ok = accepted[index] if index < len(accepted) else True
        parts.append(
            f'<circle class="il-dot {"il-ok" if ok else "il-bad"}" '
            f'cx="{axes.sx(index):.1f}" cy="{axes.sy(value):.1f}" r="3.6"/>'
        )
    return _svg(box, "".join(parts), "identity similarity across the batch")


def histogram(
    values: Sequence[float],
    *,
    bins: int = 18,
    threshold: float | None = None,
    x_label: str = "identity",
    width: float = 300.0,
    height: float = 230.0,
) -> str:
    """Distribution with the gate drawn where it actually falls."""
    if not values:
        return ""
    low = min(values)
    high = max(values)
    if threshold is not None:
        low = min(low, threshold)
        high = max(high, threshold)
    if high - low < 1e-9:
        high = low + 1.0
    edges = [low + (high - low) * index / bins for index in range(bins + 1)]
    counts = [0] * bins
    for value in values:
        slot = min(bins - 1, max(0, int((value - low) / (high - low) * bins)))
        counts[slot] += 1

    box = Box(width=width, height=height, left=34.0)
    axes = _Axes(box, (low, high), (0.0, float(max(counts)) or 1.0))
    parts = [axes.frame(x_label=x_label, y_label="frames")]
    for index, count in enumerate(counts):
        if count == 0:
            continue
        x_left = axes.sx(edges[index])
        x_right = axes.sx(edges[index + 1])
        y_top = axes.sy(float(count))
        classes = "il-bar"
        if threshold is not None and edges[index + 1] <= threshold:
            classes += " il-bad"
        parts.append(
            f'<rect class="{classes}" x="{x_left + 0.7:.1f}" y="{y_top:.1f}" '
            f'width="{max(x_right - x_left - 1.4, 1.0):.1f}" '
            f'height="{axes.sy(0.0) - y_top:.1f}"/>'
        )
    if threshold is not None:
        x = axes.sx(threshold)
        parts.append(
            f'<line class="il-threshold" x1="{x:.1f}" y1="{box.top:.1f}" '
            f'x2="{x:.1f}" y2="{axes.sy(0.0):.1f}"/>'
        )
    return _svg(box, "".join(parts), f"{x_label} distribution")


def scatter(
    xs: Sequence[float],
    ys: Sequence[float],
    *,
    accepted: Sequence[bool],
    x_threshold: float | None = None,
    y_threshold: float | None = None,
    x_label: str = "identity",
    y_label: str = "technical",
    width: float = 300.0,
    height: float = 230.0,
) -> str:
    """Two gates at once: the accept region is the top-right quadrant."""
    if not xs or not ys:
        return ""
    box = Box(width=width, height=height, left=38.0)
    x_values = [*xs, *([x_threshold] if x_threshold is not None else [])]
    y_values = [*ys, *([y_threshold] if y_threshold is not None else [])]
    axes = _Axes(
        box,
        (min(x_values) - 0.03, max(x_values) + 0.03),
        (min(y_values) - 0.03, max(y_values) + 0.03),
    )
    parts = [axes.frame(x_label=x_label, y_label=y_label)]
    if x_threshold is not None and y_threshold is not None:
        parts.append(
            f'<rect class="il-region" x="{axes.sx(x_threshold):.1f}" y="{box.top:.1f}" '
            f'width="{max(width - box.right - axes.sx(x_threshold), 0):.1f}" '
            f'height="{max(axes.sy(y_threshold) - box.top, 0):.1f}"/>'
        )
    if x_threshold is not None:
        parts.append(
            f'<line class="il-threshold" x1="{axes.sx(x_threshold):.1f}" y1="{box.top:.1f}" '
            f'x2="{axes.sx(x_threshold):.1f}" y2="{axes.sy(axes.y0):.1f}"/>'
        )
    if y_threshold is not None:
        parts.append(
            f'<line class="il-threshold" x1="{box.left:.1f}" y1="{axes.sy(y_threshold):.1f}" '
            f'x2="{width - box.right:.1f}" y2="{axes.sy(y_threshold):.1f}"/>'
        )
    for index, (x_value, y_value) in enumerate(zip(xs, ys, strict=True)):
        ok = accepted[index] if index < len(accepted) else True
        parts.append(
            f'<circle class="il-dot {"il-ok" if ok else "il-bad"}" '
            f'cx="{axes.sx(x_value):.1f}" cy="{axes.sy(y_value):.1f}" r="3.6"/>'
        )
    return _svg(box, "".join(parts), f"{y_label} against {x_label}")


def delta_bars(
    deltas: Sequence[float],
    labels: Sequence[str],
    *,
    ci: tuple[float, float] | None = None,
    width: float = 620.0,
    height: float = 260.0,
) -> str:
    """Paired differences, sorted, with the confidence interval as a band."""
    if not deltas:
        return ""
    order = sorted(range(len(deltas)), key=lambda index: deltas[index])
    sorted_deltas = [deltas[index] for index in order]
    box = Box(width=width, height=height, bottom=52.0)
    limit = max(abs(min(sorted_deltas)), abs(max(sorted_deltas)), 1e-6) * 1.15
    axes = _Axes(box, (-0.5, float(len(deltas) - 0.5)), (-limit, limit))

    parts = [
        axes.frame(
            x_label="paired cell (sorted by delta)", y_label="challenger - baseline", x_ticks=[]
        )
    ]
    if ci is not None:
        top = axes.sy(ci[1])
        bottom = axes.sy(ci[0])
        parts.append(
            f'<rect class="il-ci" x="{box.left:.1f}" y="{min(top, bottom):.1f}" '
            f'width="{box.inner_width:.1f}" height="{abs(bottom - top):.1f}"/>'
        )
    zero = axes.sy(0.0)
    parts.append(
        f'<line class="il-zero" x1="{box.left:.1f}" y1="{zero:.1f}" '
        f'x2="{width - box.right:.1f}" y2="{zero:.1f}"/>'
    )
    slot = box.inner_width / max(len(deltas), 1)
    for position, index in enumerate(order):
        value = deltas[index]
        x = axes.sx(position) - slot * 0.35
        y = axes.sy(max(value, 0.0))
        parts.append(
            f'<rect class="il-bar {"il-ok" if value > 0 else "il-bad"}" x="{x:.1f}" y="{y:.1f}" '
            f'width="{slot * 0.7:.1f}" height="{abs(axes.sy(value) - zero):.1f}">'
            f"<title>{escape(labels[index])}: {value:+.4f}</title></rect>"
        )
    return _svg(box, "".join(parts), "paired differences")
