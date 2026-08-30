# ADR-0006: Providers behind a protocol, with a synthetic renderer as the default

**Status:** accepted

## Context

An evaluation harness that needs a GPU to demonstrate itself cannot be reviewed,
cannot run in CI, and cannot be tried by anyone evaluating whether to adopt it. But
a demo that ships pre-baked numbers proves nothing at all.

## Decision

`GenerationProvider` is a two-member protocol: a name and `generate(request) ->
Candidate`. Three implementations ship:

- **synthetic** — a deterministic procedural renderer. Not a generative model: a
  simulator of a generation stack with the three behaviours a test needs — a stable
  identity, scene variety driven by prompt and seed, and *controllable failure*
  (`identity_jitter`, `drift_per_frame`, `blur`, `exposure_bias`).
- **directory** — score frames produced anywhere else, resolved by cell id.
- **comfyui** — submit a workflow, poll, fetch.

The evaluation layer knows only the protocol.

## Consequences

- `make demo` runs in ~40 s on a CPU and every number in it is computed from real
  pixels, not stored.
- "Recipe A vs recipe B" in the demo is a genuine A/B over two configurations,
  scored by the same code path a ComfyUI run takes.
- The failure knobs make the gates testable: a test can assert that a loose recipe
  is *caught*, which is the property that actually matters and the one that silently
  rots first. CI asserts it on every push.
- Someone could mistake the synthetic frames for a claim about image quality. The
  module docstring, the README and every report say otherwise.
