# ADR-0001: Describe every frame with two vectors, not one

**Status:** accepted

## Context

The obvious design is one embedding per frame and one cosine per comparison. It
fails on the first requirement: identity consistency is trivially maximised by
generating the same photograph every time, and a batch of twenty identical frames
would score perfectly on every identity metric while being worthless.

Adding a diversity metric on the *same* vector does not fix it — the metric would
then reward a batch for drifting off-model, because "different" and "different
person" are the same direction in that space.

## Decision

Every backend returns a `Descriptor` with two L2-normalised vectors:

- **identity** — subject-centred structure, texture and palette, computed on a
  centre crop with a radial subject weighting.
- **content** — global composition, lighting and colour layout, computed on the
  whole frame.

Identity metrics read the first. Diversity and shortlist novelty read the second.
No metric mixes them.

## Consequences

- A policy can demand "the same character in visibly different pictures", which is
  the actual production requirement.
- The MMR shortlist can penalise near-duplicates without ever rewarding drift.
- Backends must produce both. For a face-recognition backend the identity vector is
  the face embedding and the content vector is delegated to the classical
  descriptor — a composition, not a compromise.
- Two vectors is two things to calibrate. The content vector is only ever used for
  *relative* distances, so it needs no threshold of its own beyond `diversity_min`.
