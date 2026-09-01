# Evaluation protocol

How to run an evaluation whose result you would be willing to defend in a review.
The tool enforces some of this; the rest is yours to get right.

---

## 1. Build a reference set worth measuring against

The references are the yardstick. Everything downstream inherits their quality.

- **Six to twelve frames.** Below four, leave-one-out is too noisy to calibrate
  from and the tool says so.
- **One look.** Curate references shot under controlled conditions — the character
  as intended, not a sample of what the pipeline produced today. The bundled
  synthetic references use a fixed neutral backdrop and restrained light for exactly
  this reason.
- **Check coherence before anything else.** `identitylock calibrate` prints mean
  pairwise cosine within each reference set. Below ~0.15 the centroid is an average
  of two different people and no downstream number means anything.
- **Never let a generated take back into the reference set.** That is how a pipeline
  slowly redefines the character as whatever it currently produces.

## 2. Assemble a cohort

Add at least two other characters' reference sets. Without them there is no impostor
margin, and a high similarity is unfalsifiable: if every character in the cohort
scores 0.9 against a frame, the descriptor is measuring "a portrait".

The tool never fakes a margin. With a cohort of one it reports `None`, skips the
gate, and warns.

## 3. Keep three seed ranges disjoint

| Frames         | Seeds     | Role                                                    |
| -------------- | --------- | ------------------------------------------------------- |
| **reference**  | `9000+`   | the yardstick                                           |
| **validation** | `7000+`   | where thresholds come from                              |
| **evaluation** | the suite | what gets judged                                        |

A threshold fitted on the frames it will later judge is not a threshold, it is a
memory. `identitylock bootstrap` and `identitylock calibrate` use the ranges above;
choose evaluation seeds that overlap neither.

## 4. Calibrate, do not guess

```bash
identitylock calibrate --suite suites/mine.yaml --far 0.02 --write
```

Read three things off the output before trusting the policy it writes:

- **AUC.** Below ~0.90 the descriptor is barely separating these characters; the
  gate will reject good frames and accept bad ones roughly at random. Switch to a
  learned backend rather than lowering the threshold.
- **FRR at the chosen FAR.** This is the cost in re-renders. If a quarter of genuine
  frames would be rejected, either loosen `--far` or improve the descriptor.
- **The warnings.** "N validation frames sit closer to another character than to
  their own" counts descriptor failures. They are not generation failures and no
  amount of prompt engineering will fix them.

`--far` is a business decision: how expensive is an off-model frame reaching a feed
versus a good frame being re-rendered? Sweep it, pick the knee, write down why.

Re-calibrate whenever the embedder, the cohort, the reference sets or the render
pipeline changes. Thresholds transfer no further than the set they were fitted on.

## 5. Design the batch, not just the prompts

- **Cover the hard cases.** Low light, extreme framing, unusual wardrobe. A suite
  of four studio prompts will pass forever and catch nothing.
- **Enough seeds for the comparison you want.** Twenty-four paired cells detect an
  effect around 0.05–0.10 in identity cosine. Smaller effects need more cells, and
  a wide interval is the tool telling you so — not a reason to squint at the mean.
- **Do not reorder the plan.** It is seed-major so prompt difficulty is not aliased
  with position in the batch. That is what makes the drift slope meaningful.

## 6. Run, and read the gates rather than the headline

```bash
identitylock run --suite suites/mine.yaml --recipe v3 --gate
```

Each gate answers a different question, and they fail independently:

| Gate               | Reads                                    | Usually means                             |
| ------------------ | ---------------------------------------- | ----------------------------------------- |
| `consistency_rate` | share of takes clearing candidate gates  | too many off-model or unusable frames     |
| `identity_p05`     | the worst end of the batch               | the tail is bad even if the mean is fine  |
| `drift`            | slope + stratified permutation p         | the batch degrades as it runs             |
| `diversity`        | content spread among accepted takes      | the pipeline is producing one photograph  |

A batch can pass every run-level gate and still be wrong for you. Look at the
rejected frames.

## 7. Compare like for like

```bash
identitylock compare --baseline var/runs/v2 --challenger var/runs/v3 --gate
```

The comparison refuses to run when it would be dishonest: different suites,
different characters, different embedders, different reference sets, mismatched
cells, or the same recipe revision on both sides. Those are errors, not warnings.

Then read the interval, not the mean:

- `ci_low > 0` and the win rate and effect clear their bars → **improvement**
- `ci_high < 0` → **regression**, and `--gate` exits 1
- anything else → **inconclusive**, which is a real answer and often the right one

Pick the metric that matches the change you made. Two recipes can be identical on
`identity` and differ enormously on `technical`; comparing the wrong one produces a
confident "no difference" about a question you did not ask.

## 8. What invalidates a result

- Re-rendering references between the two runs of an A/B.
- Changing the embedder, the crop or the block weights mid-experiment.
- Calibrating on the evaluation seeds.
- Comparing runs from different suites and intersecting the cells by hand.
- Reading a mean whose interval crosses zero as a win.
- Adding characters to the cohort between runs — the identity space is refitted and
  every similarity moves.

The first four the tool blocks. The last two it can only report; that part is yours.
