# ADR-0007: Ship a classical descriptor as the default backend

**Status:** accepted

## Context

The right identity descriptor for production is a face-recognition embedding —
ArcFace or similar, where cosine has a calibrated meaning. It also drags in
`onnxruntime` or `torch`, a model download, and a GPU to be quick about it.

Making that the only option means the harness cannot be installed in a minute,
cannot run in CI, and cannot be tried before it is believed.

## Decision

The default is a dependency-free classical descriptor: oriented gradients, uniform
rotation-invariant LBP and saturation-weighted hue histograms over a
radially-weighted centre crop. It installs with numpy and pillow, and it is
deterministic to the last bit across machines.

`ClipEmbedder` and `ArcFaceEmbedder` implement the same protocol behind optional
extras. Selecting one that is not installed raises with the install line — it is
**never** silently swapped for the classical one, because a run labelled `arcface`
in its manifest must have been produced by arcface.

## Consequences

- Anyone can run the harness end to end immediately, and every number in the demo
  is a real measurement.
- The default is genuinely weaker. On the bundled cohort it reaches AUC 0.994 and
  still misplaces 2 of 48 validation frames. The docstring, the README and the
  calibration output all say so, in those words.
- The learned backends are typed and reviewable but **unexercised** — no GPU and no
  weights in CI, and a green test against a mock would only prove the mock works.
  Coverage there is 40% and the README states it.
- Because every backend passes through the same calibration and the same gates,
  swapping one changes a flag, not a workflow.
