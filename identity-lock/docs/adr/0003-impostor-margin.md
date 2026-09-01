# ADR-0003: The identity claim is the margin, not the similarity

**Status:** accepted

## Context

"This frame scores 0.9 against the character" is not a claim that can be wrong. If
every character in the cohort also scores 0.9, the descriptor is measuring "a
portrait", not "this portrait", and the gate would pass anything face-shaped.

Face verification has answered this for decades: report the genuine score against
the impostor distribution, never alone.

## Decision

Every candidate carries `identity_margin = cos(v, own centroid) − max over other
characters of cos(v, their centroid)`, together with which character was closest.
The gate reads the margin as well as the similarity.

When the cohort holds nobody else the margin is `None`, the gate is **skipped** —
never silently passed — and the report says the cohort was too small.

## Consequences

- A run requires reference sets for characters it is not evaluating. That is a real
  setup cost, and it is the cost of the claim being falsifiable.
- Negative margins are visible and countable. The calibration reports them as
  *descriptor* failures rather than generation failures, which is the honest
  attribution and points at the right fix.
- The tool can state when it is not able to separate a cohort at all, instead of
  emitting a confident threshold over an AUC of 0.6.
