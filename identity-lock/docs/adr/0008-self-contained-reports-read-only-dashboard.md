# ADR-0008: Reports are single files; the dashboard is read-only

**Status:** accepted

## Context

Two different consumers. A reviewer wants to open one artefact, now, possibly from
an email attachment six months from now. An operator iterating on recipes wants to
filter, sort and compare across runs.

A report that points at image paths stops working the moment it is moved. A
dashboard that can trigger generation is a different product with a different threat
model.

## Decision

**Reports** are single HTML files: images inlined as data URIs, charts as
hand-written inline SVG, styles in one `<style>` block, no scripts and no external
requests of any kind. A test asserts the absence of any non-`data:` URL.

**The dashboard** is a read-only FastAPI over a working directory plus a pre-built
React bundle. It never generates, scores or mutates. It recomputes nothing — every
number it shows is the number stored in `run.json` — so it and the report can never
disagree about what a run measured.

Charts are hand-written in both surfaces, sharing one visual language, rather than
pulled from a plotting library.

## Consequences

- A report survives being emailed, attached to a ticket, or opened from a USB stick.
  It costs ~150 kB for a 24-frame run, which is the right trade.
- No chart library means writing axis ticks, nice-number rounding and label
  collision avoidance by hand — around 400 lines across the two implementations, and
  the reason both surfaces look like one product.
- The dashboard bundle is committed so `pip install identity-lock[api]` works
  without a Node toolchain. CI asserts the committed bundle matches its sources, so
  it cannot drift.
- Serving a directory is safe to do casually: path traversal is blocked and tested,
  and there is no endpoint that costs GPU time.
