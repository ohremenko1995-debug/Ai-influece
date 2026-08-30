"""Self-contained HTML reports.

One file, no network, no build step: images inlined as data URIs, charts as inline
SVG, styles in a single ``<style>`` block. A report that needs a server to render
is not an artefact, and the whole point of an evaluation run is to leave something
behind that outlives the terminal it ran in.

Two things every report states without being asked: what the numbers were measured
*with* (backend, recipe revision, policy fingerprint) and what the tool could not
tell you. A report that only shows the good news is a marketing page.
"""

from __future__ import annotations

from collections.abc import Iterable
from html import escape
from pathlib import Path

from identitylock import __version__
from identitylock.domain.models import Comparison, GateOutcome, RunResult, ScoredCandidate
from identitylock.domain.policy import Policy
from identitylock.imaging.loader import thumbnail_data_uri
from identitylock.reporting.charts import delta_bars, drift_chart, histogram, scatter

_STYLE = """
:root {
  color-scheme: light dark;
  --bg: #f7f7f8; --panel: #ffffff; --ink: #17181c; --muted: #6b7078;
  --line: #e3e4e8; --ok: #1a7f52; --bad: #c0392f; --warn: #a26a00;
  --accent: #2b5fd9; --grid: #eceef2; --region: rgba(26,127,82,.07);
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #101114; --panel: #17181d; --ink: #e9eaee; --muted: #9aa0aa;
    --line: #2a2c33; --ok: #4cc38a; --bad: #f2665a; --warn: #e0a33a;
    --accent: #7aa2f7; --grid: #23252b; --region: rgba(76,195,138,.10);
  }
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--ink);
  font: 14px/1.55 ui-sans-serif, -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; }
.wrap { max-width: 1180px; margin: 0 auto; padding: 32px 20px 72px; }
h1 { font-size: 22px; margin: 0 0 4px; letter-spacing: -.01em; }
h2 { font-size: 15px; margin: 32px 0 12px; text-transform: uppercase;
  letter-spacing: .08em; color: var(--muted); font-weight: 600; }
a { color: var(--accent); }
.sub { color: var(--muted); margin: 0 0 20px; }
.panel { background: var(--panel); border: 1px solid var(--line);
  border-radius: 10px; padding: 18px; }
.verdict { display: flex; align-items: baseline; gap: 14px; flex-wrap: wrap;
  border-left: 4px solid var(--ok); padding: 14px 18px; margin-bottom: 20px; }
.verdict.fail { border-left-color: var(--bad); }
.verdict .tag { font-size: 20px; font-weight: 700; letter-spacing: .02em; color: var(--ok); }
.verdict.fail .tag { color: var(--bad); }
.verdict .why { color: var(--muted); }
.grid { display: grid; gap: 14px; }
.stats { grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); }
.stat { background: var(--panel); border: 1px solid var(--line);
  border-radius: 10px; padding: 12px 14px; }
.stat .k { color: var(--muted); font-size: 11px; text-transform: uppercase; letter-spacing: .07em; }
.stat .v { font-size: 21px; font-variant-numeric: tabular-nums; margin-top: 3px; }
.stat .n { color: var(--muted); font-size: 12px; font-variant-numeric: tabular-nums; }
.charts { grid-template-columns: 1fr; }
@media (min-width: 900px) { .charts.split { grid-template-columns: 1fr 1fr; } }
.chartcard { background: var(--panel); border: 1px solid var(--line);
  border-radius: 10px; padding: 12px 12px 4px; }
.chartcard h3 { margin: 2px 4px 6px; font-size: 13px; font-weight: 600; }
.chartcard p { margin: 0 4px 10px; color: var(--muted); font-size: 12px; }
.il-chart { width: 100%; height: auto; display: block; }
.il-grid { stroke: var(--grid); stroke-width: 1; }
.il-tick { fill: var(--muted); font-size: 10px; }
.il-axis { fill: var(--muted); font-size: 11px; }
.il-dot.il-ok { fill: var(--ok); fill-opacity: .85; }
.il-dot.il-bad { fill: var(--bad); fill-opacity: .9; }
.il-bar { fill: var(--accent); fill-opacity: .75; }
.il-bar.il-ok { fill: var(--ok); fill-opacity: .8; }
.il-bar.il-bad { fill: var(--bad); fill-opacity: .8; }
.il-threshold { stroke: var(--bad); stroke-width: 1.4; stroke-dasharray: 5 4; }
.il-threshold-label { fill: var(--bad); }
.il-trend { stroke: var(--accent); stroke-width: 2; }
.il-zero { stroke: var(--line); stroke-width: 1.4; }
.il-ci { fill: var(--accent); fill-opacity: .12; }
.il-region { fill: var(--region); }
table { width: 100%; border-collapse: collapse; font-variant-numeric: tabular-nums; }
th, td { text-align: left; padding: 8px 10px;
  border-bottom: 1px solid var(--line); font-size: 13px; }
th { color: var(--muted); font-weight: 600; font-size: 11px;
  text-transform: uppercase; letter-spacing: .06em; }
td.num, th.num { text-align: right; }
.pill { display: inline-block; padding: 1px 8px; border-radius: 999px; font-size: 11px;
  font-weight: 600; letter-spacing: .03em; }
.pill.ok { background: color-mix(in srgb, var(--ok) 16%, transparent); color: var(--ok); }
.pill.bad { background: color-mix(in srgb, var(--bad) 16%, transparent); color: var(--bad); }
.pill.warn { background: color-mix(in srgb, var(--warn) 18%, transparent); color: var(--warn); }
.gallery { display: grid; gap: 12px; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); }
.card { background: var(--panel); border: 1px solid var(--line); border-radius: 10px;
  overflow: hidden; }
.card.rejected { opacity: .62; }
.card.selected { outline: 2px solid var(--accent); outline-offset: -2px; }
.card img { width: 100%; aspect-ratio: 1; object-fit: cover;
  display: block; background: var(--grid); }
.card .meta { padding: 8px 10px 10px; font-size: 11.5px; }
.card .meta b { font-variant-numeric: tabular-nums; }
.card .why { color: var(--bad); margin-top: 4px; font-size: 11px; }
.meta-list { display: grid; gap: 2px 18px;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  font-size: 12.5px; }
.meta-list div { display: flex; justify-content: space-between; gap: 12px;
  border-bottom: 1px dotted var(--line); padding: 4px 0; }
.meta-list span:first-child { color: var(--muted); }
.meta-list code { font-size: 11.5px; }
.notes { color: var(--muted); font-size: 12.5px; }
.notes li { margin-bottom: 6px; }
footer { margin-top: 40px; color: var(--muted); font-size: 12px;
  border-top: 1px solid var(--line); padding-top: 14px; }
"""


def _pill(passed: bool, label: str | None = None) -> str:
    text = label or ("pass" if passed else "fail")
    return f'<span class="pill {"ok" if passed else "bad"}">{escape(text)}</span>'


def _stat(key: str, value: str, note: str = "") -> str:
    note_html = f'<div class="n">{escape(note)}</div>' if note else ""
    return (
        f'<div class="stat"><div class="k">{escape(key)}</div>'
        f'<div class="v">{escape(value)}</div>{note_html}</div>'
    )


def _gate_rows(gates: Iterable[GateOutcome]) -> str:
    rows = []
    for gate in gates:
        observed = "—" if gate.observed is None else f"{gate.observed:.4f}"
        threshold = "—" if gate.threshold is None else f"{gate.threshold:.4f}"
        rows.append(
            f"<tr><td>{_pill(gate.passed)}</td><td><code>{escape(gate.name)}</code></td>"
            f'<td class="num">{observed}</td><td class="num">{threshold}</td>'
            f'<td class="notes">{escape(gate.detail)}</td></tr>'
        )
    return (
        '<table><thead><tr><th></th><th>gate</th><th class="num">observed</th>'
        '<th class="num">threshold</th><th>what it means</th></tr></thead>'
        f"<tbody>{''.join(rows)}</tbody></table>"
    )


def _manifest_rows(result: RunResult, policy: Policy | None) -> str:
    manifest = result.manifest
    items = [
        ("run id", f"<code>{escape(result.run_id)}</code>"),
        ("generated", escape(manifest.created_at.strftime("%Y-%m-%d %H:%M:%S UTC"))),
        (
            "character",
            f"{escape(result.suite.character.name)} "
            f"(<code>{escape(result.suite.character.id)}</code>)",
        ),
        ("cohort", escape(", ".join(result.suite.cohort_ids) or "—")),
        ("provider", f"<code>{escape(manifest.provider)}</code>"),
        ("embedder", f"<code>{escape(manifest.embedder)}</code> · {manifest.embedder_dim}d"),
        (
            "recipe",
            f"{escape(result.suite.recipe.name)} · <code>{escape(manifest.recipe_revision)}</code>",
        ),
        ("policy fingerprint", f"<code>{escape(manifest.policy_hash)}</code>"),
        ("references", f"{len(manifest.reference_hashes)} frames"),
        (
            "tool",
            f"identity-lock {escape(manifest.tool_version)} · "
            f"python {escape(manifest.python_version)}",
        ),
    ]
    if policy is not None:
        items.append(
            (
                "gates",
                f"identity &#8805; {policy.identity_min:.4f}"
                f" · margin &#8805; {policy.margin_min:.4f}"
                f" · technical &#8805; {policy.technical_min:.2f}",
            )
        )
    return (
        '<div class="meta-list">'
        + "".join(f"<div><span>{key}</span><span>{value}</span></div>" for key, value in items)
        + "</div>"
    )


def _card(item: ScoredCandidate, *, thumbnails: bool) -> str:
    metrics = item.metrics
    classes = ["card"]
    if item.decision == "reject":
        classes.append("rejected")
    if item.selected:
        classes.append("selected")

    image = ""
    if thumbnails and Path(item.candidate.image_path).is_file():
        uri = thumbnail_data_uri(Path(item.candidate.image_path), size=240)
        image = f'<img src="{uri}" alt="{escape(item.candidate.id)}" loading="lazy"/>'

    margin = "—" if metrics.identity_margin is None else f"{metrics.identity_margin:+.3f}"
    why = ""
    if item.rejections:
        why = f'<div class="why">{escape("; ".join(item.rejections))}</div>'
    badge = _pill(
        item.decision == "accept", "accepted" if item.decision == "accept" else "rejected"
    )
    star = ' <span class="pill warn">shortlist</span>' if item.selected else ""

    return (
        f'<div class="{" ".join(classes)}">{image}<div class="meta">'
        f"{badge}{star}<br/>"
        f"<code>{escape(item.candidate.prompt_id)}</code> · seed {item.candidate.seed}<br/>"
        f"id <b>{metrics.identity_similarity:+.3f}</b> · margin <b>{margin}</b><br/>"
        f"tech <b>{metrics.technical_score:.3f}</b>{why}</div></div>"
    )


def _rejection_summary(result: RunResult) -> str:
    reasons: dict[str, int] = {}
    for item in result.candidates:
        for reason in item.rejections:
            key = reason.split(" ")[0]
            reasons[key] = reasons.get(key, 0) + 1
    if not reasons:
        return '<p class="notes">No candidate was rejected.</p>'
    rows = "".join(
        f'<tr><td><code>{escape(name)}</code></td><td class="num">{count}</td></tr>'
        for name, count in sorted(reasons.items(), key=lambda item: -item[1])
    )
    return (
        '<table><thead><tr><th>failing check</th><th class="num">frames</th></tr></thead>'
        f"<tbody>{rows}</tbody></table>"
    )


def render_run_report(
    result: RunResult,
    *,
    policy: Policy | None = None,
    thumbnails: bool = True,
    limitations: Iterable[str] = (),
) -> str:
    """Render one run as a standalone HTML document."""
    aggregates = result.aggregates
    identity = [item.metrics.identity_similarity for item in result.candidates]
    technical = [item.metrics.technical_score for item in result.candidates]
    accepted = [item.decision == "accept" for item in result.candidates]
    threshold = policy.identity_min if policy else min(identity, default=0.0)
    technical_threshold = policy.technical_min if policy else None

    verdict_class = "verdict panel" + ("" if result.verdict.passed else " fail")
    failed = ", ".join(result.verdict.failed_gates)
    why = "Every gate cleared." if result.verdict.passed else f"Failed gates: {failed}."

    cards = "".join(_card(item, thumbnails=thumbnails) for item in result.candidates)
    default_limitations = [
        "Identity similarity is measured with the descriptor named in the manifest. "
        "Numbers from two different backends are not comparable.",
        "Thresholds are calibrated on a validation set, not derived from first "
        "principles; re-run <code>identitylock calibrate</code> after changing the "
        "reference sets, the cohort or the backend.",
        "A passing run means the batch cleared the stated gates. It is not a "
        "statement about likeness to any real person, and no gate here checks that.",
    ]

    notes = "".join(f"<li>{note}</li>" for note in (list(limitations) or default_limitations))

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Identity Lock — {escape(result.run_id)}</title>
<style>{_STYLE}</style></head><body><div class="wrap">
<h1>Identity Lock — {escape(result.suite.character.name)}</h1>
<p class="sub">{escape(result.label)} · suite <code>{escape(result.suite.id)}</code> ·
{escape(result.suite.character.disclosure)}</p>

<div class="{verdict_class}">
  <span class="tag">{"PASS" if result.verdict.passed else "FAIL"}</span>
  <span class="why">{escape(why)}</span>
</div>

<div class="grid stats">
  {
        _stat(
            "identity (mean)",
            f"{aggregates.identity_mean:+.3f}",
            f"95% CI [{aggregates.identity_ci_low:+.3f}, {aggregates.identity_ci_high:+.3f}]",
        )
    }
  {_stat("identity p05", f"{aggregates.identity_p05:+.3f}", f"min {aggregates.identity_min:+.3f}")}
  {
        _stat(
            "impostor margin",
            "—" if aggregates.margin_mean is None else f"{aggregates.margin_mean:+.3f}",
            "mean over the cohort",
        )
    }
  {
        _stat(
            "consistency",
            f"{aggregates.consistency_rate:.0%}",
            f"{aggregates.n_accepted}/{aggregates.n_total} accepted",
        )
    }
  {_stat("technical", f"{aggregates.technical_mean:.3f}", "sharpness / exposure / contrast")}
  {
        _stat(
            "drift per 10",
            f"{aggregates.drift_slope:+.4f}",
            f"p={aggregates.drift_p_value:.3f}, R²={aggregates.drift_r2:.2f}",
        )
    }
  {_stat("diversity", f"{aggregates.diversity:.3f}", "mean pairwise content distance")}
  {_stat("shortlist", str(len(result.selected)), "MMR over accepted takes")}
</div>

<h2>Gates</h2>
<div class="panel">{_gate_rows(result.verdict.gates)}</div>

<h2>Identity across the batch</h2>
<div class="grid charts">
  <div class="chartcard">
    <h3>Identity by position</h3>
    <p>Prompts are interleaved, so a slope here is degradation over the batch and not
       the prompt list running out of easy shots. Dashed line is the accept threshold;
       the straight line is the fitted trend after prompt effects are removed.</p>
    {
        drift_chart(
            identity, accepted=accepted, threshold=threshold, slope_per_10=aggregates.drift_slope
        )
    }
  </div>
</div>
<div class="grid charts split">
  <div class="chartcard">
    <h3>Distribution</h3>
    <p>What the batch looks like as a whole. The fifth percentile, not the mean, is
       what the run-level gate reads.</p>
    {histogram(identity, threshold=threshold)}
  </div>
  <div class="chartcard">
    <h3>Identity against technical quality</h3>
    <p>Two independent ways to fail. The shaded quadrant is the region where a frame
       clears both gates.</p>
    {
        scatter(
            identity,
            technical,
            accepted=accepted,
            x_threshold=threshold,
            y_threshold=technical_threshold,
        )
    }
  </div>
</div>

<h2>Why frames were rejected</h2>
<div class="panel">{_rejection_summary(result)}</div>

<h2>Every take</h2>
<div class="gallery">{cards}</div>

<h2>Provenance</h2>
<div class="panel">{_manifest_rows(result, policy)}</div>

<h2>What this report does not tell you</h2>
<div class="panel"><ul class="notes">{notes}</ul></div>

<footer>Generated by identity-lock {escape(__version__)}. All imagery in this report is
AI-generated; the characters are openly virtual and depict no real person.</footer>
</div></body></html>
"""


def render_comparison_report(
    comparison: Comparison,
    *,
    baseline: RunResult | None = None,
    challenger: RunResult | None = None,
) -> str:
    """Render a paired A/B as a standalone HTML document."""
    outcome = comparison.verdict.outcome
    verdict_class = "verdict panel" + ("" if outcome == "improvement" else " fail")
    labels = [f"{pair.prompt_id} · seed {pair.seed}" for pair in comparison.pairs]
    deltas = [pair.delta for pair in comparison.pairs]

    rows = "".join(
        f"<tr><td><code>{escape(pair.prompt_id)}</code></td>"
        f'<td class="num">{pair.seed}</td>'
        f'<td class="num">{pair.baseline:+.4f}</td>'
        f'<td class="num">{pair.challenger:+.4f}</td>'
        f'<td class="num">{pair.delta:+.4f}</td>'
        f"<td>{_pill(pair.delta > 0, 'win' if pair.delta > 0 else 'loss')}</td></tr>"
        for pair in sorted(comparison.pairs, key=lambda item: item.delta)
    )

    context = ""
    if baseline is not None and challenger is not None:
        context = (
            '<div class="meta-list">'
            f"<div><span>baseline recipe</span><span><code>"
            f"{escape(baseline.manifest.recipe_revision)}</code></span></div>"
            f"<div><span>challenger recipe</span><span><code>"
            f"{escape(challenger.manifest.recipe_revision)}</code></span></div>"
            f"<div><span>baseline verdict</span><span>"
            f"{_pill(baseline.verdict.passed)}</span></div>"
            f"<div><span>challenger verdict</span><span>"
            f"{_pill(challenger.verdict.passed)}</span></div>"
            "</div>"
        )

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Identity Lock — {escape(comparison.comparison_id)}</title>
<style>{_STYLE}</style></head><body><div class="wrap">
<h1>{escape(comparison.challenger_label)} vs {escape(comparison.baseline_label)}</h1>
<p class="sub">Paired A/B on <code>{escape(comparison.metric)}</code> ·
{comparison.n_pairs} cells · same prompts, same seeds, same references.</p>

<div class="{verdict_class}">
  <span class="tag">{escape(outcome.upper())}</span>
  <span class="why">{escape(comparison.verdict.rationale)}</span>
</div>

<div class="grid stats">
  {_stat("win rate", f"{comparison.win_rate:.0%}", f"{comparison.n_pairs} paired cells")}
  {_stat("mean delta", f"{comparison.mean_delta:+.4f}", "challenger minus baseline")}
  {
        _stat(
            "95% CI",
            f"[{comparison.ci_low:+.4f}, {comparison.ci_high:+.4f}]",
            "percentile bootstrap",
        )
    }
  {_stat("effect size", f"{comparison.effect_size:+.3f}", "matched-pairs rank-biserial")}
</div>

<h2>Every paired cell</h2>
<div class="chartcard">
  <p>One bar per cell, sorted. The shaded band is the confidence interval for the
     mean difference — when it crosses zero, the comparison is inconclusive no matter
     how the bars look.</p>
  {delta_bars(deltas, labels, ci=(comparison.ci_low, comparison.ci_high))}
</div>

<h2>Gates</h2>
<div class="panel">{_gate_rows(comparison.verdict.gates)}</div>

<h2>Cells</h2>
<div class="panel"><table><thead><tr><th>prompt</th><th class="num">seed</th>
<th class="num">baseline</th><th class="num">challenger</th><th class="num">delta</th>
<th></th></tr></thead><tbody>{rows}</tbody></table></div>

{f'<h2>Runs compared</h2><div class="panel">{context}</div>' if context else ""}

<footer>Generated by identity-lock {escape(__version__)}. Paired design: every cell is
the same prompt and seed on both sides, so the difference is the recipe.</footer>
</div></body></html>
"""
