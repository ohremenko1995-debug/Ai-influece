# ADR-0002: Measure identity in a cohort-centred space

**Status:** accepted

## Context

Histogram-based descriptors are non-negative and share a large component that every
natural image has: mid-grey luminance, a broad edge distribution, a skin-ish hue
mass. Cosine between the raw vectors of any two portraits sits near 0.95, and the
part that distinguishes two characters is buried in the third decimal — where it is
indistinguishable from JPEG noise.

Options considered: rescale the similarity range post hoc (hides the problem, does
not fix the signal-to-noise ratio); PCA-whiten (more machinery, needs enough
references to estimate a covariance, harder to explain); mean-centre.

## Decision

Fit a mean over **every reference vector in the cohort, all characters pooled**, and
project as `v ↦ normalise(v − m)`. The fitted transform is fingerprinted and its
identity travels in the run manifest.

Pooling across characters is load-bearing. Centring on a single character's own
references would subtract exactly what distinguishes them.

A backend whose cosine is already calibrated can opt out with `IdentitySpace.unit`.

## Consequences

- Similarities spread across a usable range; on the bundled cohort the identity
  gate operates near 0.14 with a genuine/impostor AUC of 0.994.
- Similarity values are **relative to a cohort**. Adding a character refits the
  space and moves every number, so a comparison across different cohorts is
  meaningless — and the harness refuses it via the reference-hash check.
- The transform is one vector, cheap to compute and trivial to explain, which
  matters more here than the extra separation whitening might buy.
