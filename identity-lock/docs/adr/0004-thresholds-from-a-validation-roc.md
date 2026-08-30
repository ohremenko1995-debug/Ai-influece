# ADR-0004: Derive thresholds from a labelled validation set

**Status:** accepted

## Context

Three ways to pick `identity_min`:

1. **A constant.** Fast, indefensible, wrong the moment the backend changes.
2. **From the reference set** (leave-one-out, take a low percentile). Principled,
   and empirically far too strict: on the bundled cohort the reference floor is
   ~0.72 while production frames — same character, different background, light and
   framing — land near 0.40. A gate at 0.72 rejects everything.
3. **From a labelled validation set**, reading the threshold off the ROC curve at a
   chosen false-accept rate. This is the standard face-verification answer and the
   only one that survives the studio-to-production shift.

## Decision

`identitylock calibrate` renders a validation set on **seeds disjoint from both the
references and the evaluated suite**, scores genuine and impostor pairs, and derives:

| Threshold              | From                                                    |
| ---------------------- | ------------------------------------------------------- |
| `identity_min`         | lowest threshold with FAR ≤ `--far` (default 2%)        |
| `identity_p05_min`     | `identity_min − 0.05`                                   |
| `margin_min`           | 5th percentile of genuine margins, floored at 0.02      |
| `consistency_rate_min` | `1 − FRR − 0.05`, clipped to [0.50, 0.95]               |

Leave-one-out is kept, for a different job: auditing whether the reference set is
internally coherent enough to be a target at all.

`technical_min`, `drift_abs_max`, `drift_alpha` and `diversity_min` are **not**
derived. They are product decisions and live in the suite file with a comment.

## Consequences

- Calibration costs a render pass. It is worth it, and it is one command.
- `consistency_rate_min` cannot demand a pass rate the descriptor does not reach on
  known-good frames — a subtle failure this derivation removes by construction.
- `--far` becomes an explicit business decision: an off-model frame in a feed versus
  a good frame re-rendered. Better an argument about that than a magic constant.
- Thresholds transfer no further than the set they were fitted on, and the docs say
  so in three places.
