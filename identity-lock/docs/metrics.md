# Metrics

Every number Identity Lock reports, with its formula, its constants and the reason
it is shaped the way it is. A score whose definition is not published is a vibe,
not a metric.

Notation: an image is `I` with pixels in `[0,1]`, `Y` is its Rec. 709 luminance,
`‖·‖` is the Euclidean norm, and `⟨a,b⟩` is the dot product.

---

## 1. Frame measurements

All of these live in `identitylock.imaging.stats`, return values in `[0,1]`, and
point the same way: higher is better.

### Sharpness

```
L      = ∇²Y                          (4-neighbour discrete Laplacian, interior only)
v      = Var(L)
score  = 1 − exp(−v / τ)              τ = 1.5e-3
```

Variance of the Laplacian is the standard no-reference focus measure. It is
unbounded and scale-dependent, so it is *squashed* rather than clipped: a
saturating curve keeps a very sharp frame distinguishable from a merely sharp one
instead of flattening everything above the threshold to 1.0.

The Laplacian is computed on the interior only — no padding — so the border does
not invent an edge. It is exactly zero on a flat field and on a linear ramp, which
is the property a focus measure must have.

### Exposure

```
μ      = mean(Y)
score  = exp(−(μ − 0.5)² / (2σ²))     σ = 0.18
```

A Gaussian centred on mid-grey: 1.0 at `μ = 0.5`, falling off symmetrically. Both
crushed and blown frames are penalised, and neither is preferred over the other.

### Contrast

```
score  = clip(std(Y) / 0.25, 0, 1)
```

A well-exposed photograph typically lands near `std(Y) ≈ 0.2–0.25`, so the
reference spread is 0.25 and everything above it is equally good.

### Colourfulness

```
rg     = R − G
yb     = ½(R + G) − B
M      = √(σ²_rg + σ²_yb) + 0.3·√(μ²_rg + μ²_yb)      (Hasler & Süsstrunk, 2003)
score  = clip(M / 0.30, 0, 1)
```

**Reported but deliberately excluded from the composite.** A colourful frame is not
a better frame, it is a different frame. It belongs in the report so a reviewer can
spot a palette shift, not in a quality gate.

### Clipping and entropy

```
clipping = P(pixel ≤ 1/255) + P(pixel ≥ 254/255)
entropy  = −Σ p·log₂p / 6            over the 64-bin histogram of Y
```

### Technical score

```
headroom  = clip(1 − clipping / 0.02, 0, 1)
technical = 0.40·sharpness + 0.25·exposure + 0.20·contrast + 0.15·headroom
```

Clipping enters as *headroom* so every term points the same way and the composite
is a plain weighted mean with no sign juggling. The weights sum to 1.0 and are an
editorial choice, not a fitted parameter: sharpness dominates because a soft frame
is unusable regardless of everything else.

---

## 2. The descriptor

`identitylock.embeddings.classical.ClassicalEmbedder` produces two L2-normalised
vectors per frame. Nothing about the metric layer depends on which backend produced
them.

### Identity vector — 292 dimensions

Computed on the central **50%** crop of the frame, resampled to 96×96. The crop
fraction was swept over `{0.42, 0.50, 0.58, 0.62, 0.72}` on the bundled cohort;
0.50 maximised the impostor margin, because a wider crop lets the background —
which is scene, not identity — into the hue histogram. Reproduce the sweep with
`identitylock calibrate`.

A radial Gaussian weight (σ = 0.55 in half-crop units) multiplies every pixel's vote
before histogramming. The subject sits in the middle and the corners are backdrop;
this is a cheap, explicit stand-in for the segmentation mask a production pipeline
would use, and it is what stops a change of background from reading as a change of
person.

| Block                        | Construction                                                                            | Dims | Weight |
| ---------------------------- | --------------------------------------------------------------------------------------- | ---- | ------ |
| Oriented gradients (HOG-lite) | 4×4 cells, 9 unsigned orientation bins, magnitude-weighted, each cell L2-normalised     | 144  | 0.55   |
| Hue histogram                | 3×3 tiles, 12 bins, weighted by `saturation × value × radial`, each tile L2-normalised   | 108  | 0.30   |
| LBP texture                  | rotation-invariant uniform LBP (P=8, 10 bins) over 2×2 tiles                             | 40   | 0.15   |

Each block is normalised *before* concatenation — otherwise the longest histogram
would dominate the cosine purely because it has more bins — then the weighted
concatenation is normalised again.

Three deliberate choices:

- **Hard orientation binning**, not the trilinear interpolation of the original HOG.
  The grid is coarse (4×4 cells over 96 px) and the interpolation buys precision the
  downstream cosine cannot use.
- **Saturation×value weighting** on hue. The hue of a near-grey or near-black pixel
  is numerically defined and visually meaningless; letting it vote adds pure noise.
- **Rotation-invariant LBP.** A tilted head should not read as a different texture.

### Content vector — 77 dimensions

Computed on the whole frame at 96×96: a 6×6 grid of tile luminance means (layout,
36), global hue/saturation/value histograms (palette, 32) and a 3×3 grid of mean
gradient magnitude (edge density, 9), weighted 0.50 / 0.30 / 0.20.

This is the vector diversity and shortlisting are measured in — never the identity
vector. Penalising identity similarity in the shortlist would reward it for
drifting off-model.

---

## 3. The identity space

Raw histogram descriptors share a large component that every natural image has:
mid-grey luminance, a broad edge distribution, a skin-ish hue mass. Cosine against
the raw vectors sits near 0.95 for *any* two portraits and the signal that matters
is buried in the third decimal.

```
m       = mean over every reference vector in the cohort, all characters pooled
project(v) = (v − m) / ‖v − m‖
```

Centring on the cohort mean removes the shared component; what remains is what
makes this character different from the others being tracked. This is the standard
"centre then renormalise" step from face-verification pipelines, done explicitly and
fingerprinted into the run manifest rather than hidden inside a backend.

Pooling across characters is essential. Centring on a single character's own
references would subtract exactly what distinguishes them and drive every
similarity toward zero.

A backend whose cosine is already calibrated (ArcFace) can skip the step with
`IdentitySpace.unit(dim)`.

---

## 4. Identity measurements

Given projected vectors and a character's reference set `R`:

```
centroid c   = normalise(mean(R))
similarity   = cos(v, c)
nearest_ref  = max over r ∈ R of cos(v, r)
coherence    = mean over pairs (r_i, r_j), i<j, of cos(r_i, r_j)
margin       = cos(v, c_own) − max over other characters k of cos(v, c_k)
```

**Coherence** is a property of the references, not of any generated take, and it is
the first number to look at when results look wrong: a centroid built from
references that disagree with each other is not a target, it is an average of two
different people. The calibration warns below 0.15.

**Nearest reference** complements the centroid. A take can sit far from the average
of the references while matching one of them closely, which usually means the
reference set spans two looks rather than one.

**Margin** is the falsifiable claim. When the cohort holds nobody else it is `None`
and the gate is *skipped* — never silently passed — and the run report says the
cohort was too small.

### Diversity

```
D(a,b)    = 1 − cos(a, b)               on content vectors
diversity = mean of D over all unordered pairs of accepted takes
```

Measured only over *accepted* takes: the diversity of a batch of rejects is not
interesting. `duplicate_pairs` additionally lists index pairs closer than 0.02,
because a batch that passes the diversity gate on average can still contain two
frames that are the same picture.

---

## 5. Drift

Drift is "identity slides as the batch progresses". Two confounds have to be
removed before that sentence means anything.

**The plan is interleaved.** `Suite.plan` is seed-major: every prompt once, then
every prompt again with the next seed. A prompt-major plan puts the hardest prompt
at the end of the batch and aliases position with difficulty.

**Prompt effects are removed and the null is stratified.** With `g(i)` the prompt of
observation `i`:

```
residual r_i = y_i − mean{ y_j : g(j) = g(i) }
x_c          = index − mean(index)
slope        = ⟨x_c, r − mean(r)⟩ / ⟨x_c, x_c⟩ × 10        (per 10 frames)
R²           = 1 − SS_res / SS_tot                          (of that fit)
p            = (1 + #{ |slope(π(r))| ≥ |slope(r)| }) / (1 + K),  K = 5000
```

where `π` reshuffles values **within each prompt group only**. Shuffling across
groups would build a null in which the prompt mix itself varies, making the observed
slope look extreme for a reason unrelated to drift.

The add-one correction keeps `p` strictly positive: no finite resampling can prove
`p = 0`.

### The gate

```
fail  ⟺  |slope| > drift_abs_max  AND  p < drift_alpha
```

Both, not either. Magnitude alone fires on noise; significance alone fires on a
slope of 0.001 once the batch is large enough. `drift_abs_max` is a product
decision — "the character may lose at most this much similarity over ten frames" —
not a fitted value.

---

## 6. Aggregation and comparison

### Batch statistics

Percentiles are the honest summary; means flatter. The run gate reads
`identity_p05`, not `identity_mean`, because the worst takes are the ones that
reach a feed.

The reported interval is a **percentile bootstrap** of the mean over 10 000
resamples with a fixed seed, so the same run always yields the same interval. The
percentile method rather than BCa: it is transparent, needs no jackknife pass, and
agrees closely with BCa on the near-symmetric paired differences this harness
bootstraps. For a heavily skewed statistic, prefer BCa — this is a stated limit,
not an oversight.

### Paired A/B

Every cell is the same prompt and the same seed under two recipes, so the
difference cannot be explained by "it drew a different picture". Pairing is not a
nicety: an unpaired comparison of twenty frames per side is dominated by scene
variance and would need an order of magnitude more samples to see the same effect.

```
δ_i        = challenger_i − baseline_i
win rate   = (#{δ > 0} + ½·#{δ = 0}) / n
mean δ     with a percentile bootstrap CI over the δ's
effect     = matched-pairs rank-biserial correlation
           = (Σ ranks of positive δ − Σ ranks of negative δ) / Σ all ranks,
             ranks taken on |δ| with zeros dropped
```

Rank-biserial rather than Cohen's d (no normality assumption) and rather than
two-sample Cliff's delta (throwing away the pairing would inflate the variance for
no reason). `cliffs_delta` is provided for genuinely unpaired comparisons.

### The verdict

```
regression   ⟺  ci_high < 0
improvement  ⟺  ci_low > 0  AND  win_rate ≥ min_win_rate
                AND |effect| ≥ min_effect_size  AND mean δ > 0
otherwise    inconclusive
```

The confidence interval is the arbiter, not the mean. A challenger that wins on
average but whose interval straddles zero is *inconclusive*, and saying so is the
entire value of running the comparison.

---

## 7. Threshold calibration

### Reference-only (leave-one-out)

For each reference, build the centroid of the *others* and score the held-out one
against it. Scoring a reference against a centroid it helped build inflates the
number; that is the leak this avoids. The resulting distribution describes how tight
the golden set is.

This is the right tool for *auditing a reference set* and the wrong tool for setting
a threshold: production frames differ from studio references in every way except the
character, so a threshold read off reference coherence rejects everything.

### Validation-based (ROC)

```
genuine   = { cos(v, c_own)   : v ∈ validation frames of that character }
impostor  = { cos(v, c_other) : the same frames against every other centroid }
AUC       = Mann-Whitney U / (n_g · n_i)          = P(genuine > impostor) + ½P(tie)
EER       = min over thresholds of max(FAR, FRR)  capped at 0.5
threshold = lowest t with FAR(t) ≤ target_far
```

EER is defined as `min max(FAR, FRR)` rather than the crossing point because ties in
the score sets make the DET curve a step function where no threshold equalises the
two rates exactly. The cap at 0.5 reflects that a coin flip always achieves 0.5.

The threshold is the *lowest* one meeting the target: raising it further only
rejects more genuine frames for no gain.

Derived from the same pass:

```
identity_min          = threshold at target_far
identity_p05_min      = identity_min − 0.05
margin_min            = max(0.02, 5th percentile of genuine margins)
consistency_rate_min  = clip(1 − FRR − 0.05, 0.50, 0.95)
```

`consistency_rate_min` matters: the batch gate cannot demand a pass rate the
descriptor does not reach on known-good frames. At FAR `target_far` it rejects
`FRR` of genuine frames, so anything above `1 − FRR` would fail a perfect generator.

### Bundled demo, for reference

| | |
| --- | --- |
| verification AUC | 0.9939 |
| EER | 4.17% at threshold +0.1210 |
| operating point | FAR target 2% → achieved 1.39%, FRR 4.17% |
| `identity_min` | 0.1438 |
| `margin_min` | 0.0344 |
| `consistency_rate_min` | 0.9083 |
| honest warning | 2 of 48 validation frames sit closer to another character than to their own |

Those two frames are descriptor failures, not generation failures, and the
calibration says so rather than rounding them away.
