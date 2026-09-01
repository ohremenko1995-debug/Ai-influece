# ADR-0005: Test drift against a stratified permutation null

**Status:** accepted

## Context

The first implementation fit a least-squares slope of identity against frame index
and failed the batch when `|slope|` exceeded a constant. It fired on a run with no
drift at all.

The cause was the experiment design, not the statistic. The plan iterated
prompt-major, so the hardest prompt sat at the end of every batch and position was
perfectly aliased with prompt difficulty. The slope was measuring the order of the
prompt list.

The second problem was the threshold. A fitted "noise ceiling" from a validation set
of twelve frames is far too permissive for a batch of twenty-four, because slope
noise shrinks with sample size — the ceiling has to be a property of the batch being
judged.

## Decision

Three changes, all needed:

1. **`Suite.plan` is seed-major.** Every prompt once, then every prompt again with
   the next seed, so prompt difficulty spreads evenly across the index.
2. **Group centring.** Each prompt's mean is subtracted before the slope is fitted.
3. **Stratified permutation test.** The null reshuffles values *within* each prompt
   group only, over 5000 permutations with a fixed seed. Shuffling across groups
   would build a null in which the prompt mix varies, making the observed slope look
   extreme for a reason unrelated to drift.

The gate then requires **both** practical and statistical significance:
`|slope| > drift_abs_max AND p < drift_alpha`.

## Consequences

- The gate no longer fires on prompt ordering. On the demo, a clean recipe reports
  p = 0.29 and a drifting one p = 0.001 with a slope three times larger.
- Requiring both conditions means a huge but random slope passes and a tiny but
  significant one passes. Both are correct: neither is a batch anyone should reject.
- The plan order is now part of the contract, and reordering it silently invalidates
  every drift number. It is documented on `Suite.plan` and in the protocol.
- 5000 permutations cost milliseconds because the fit is one matrix product.
