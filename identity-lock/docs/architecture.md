# Architecture

## Dependency direction

```
        ┌────────┐
        │ domain │   models + policy. Imports nothing above it.
        └───┬────┘
   ┌────────┴────────┐
┌──▼──────┐   ┌──────▼─────┐
│ imaging │   │ embeddings │   pixels in, numbers and vectors out
└──┬──────┘   └──────┬─────┘
   └────────┬────────┘
       ┌────▼────┐
       │ metrics │   statistics, identity space, calibration, diversity
       └────┬────┘
       ┌────▼──────┐
       │ selection │   MMR shortlisting
       └────┬──────┘
      ┌─────▼──────┐        ┌───────────┐
      │ evaluation │◄───────│ providers │   the only layer that produces images
      └─────┬──────┘        └───────────┘
   ┌─────────┼─────────┐
┌──▼──────┐ ┌▼──┐ ┌────▼┐
│reporting│ │api│ │ cli │
└─────────┘ └───┘ └─────┘
```

Nothing in `domain` imports from a layer above it, and no layer reaches down into a
provider. `providers` is the only package that writes an image, and `evaluation` is
the only package that calls it.

## The four rules

**1. The evaluation layer never talks to a model.** It asks a provider for a
candidate and gets back a file on disk plus the inputs that produced it. Swapping a
procedural renderer for a remote ComfyUI box changes one flag and nothing else,
which is what makes metrics comparable across backends.

**2. The policy never looks at an image.** `domain.policy` takes numbers that are
already measured and applies a written rule. That separation is what lets a policy
be re-applied to an archived run without regenerating anything, and it is why the
gates are testable without a single pixel.

**3. Recipes are content-addressed, not edited.** `Recipe.revision` is derived from
the fields that change what comes out of the model, computed *after* defaults are
applied, and recomputed on every load. A caller-supplied revision is overwritten, so
a report cannot claim a revision its own fields do not produce.

**4. A comparison that cannot be honest refuses to run.** Different suites,
characters, embedders or reference hashes, mismatched cells, or the same recipe on
both sides are errors. A comparison that silently intersects two different suites is
worse than no comparison, because it still prints a confident number.

## Request lifecycle of a run

1. **Load the suite.** Every consistency check that does not need the filesystem
   happens here, so a typo in a character id fails in a hundred milliseconds rather
   than after a batch of renders.
2. **Describe the references and fit the identity space** — before a single
   candidate exists, so the yardstick cannot be influenced by what it measures.
3. **Build one profile per character**: centroid, coherence, reference hashes.
4. **Walk the plan in order**, one provider call per cell. Order matters: the drift
   slope means "across this batch, in this sequence".
5. **Score each candidate**: project into the identity space, similarity, nearest
   reference, impostor margin, frame statistics, technical composite.
6. **Gate each candidate** against the policy, collecting every reason it failed.
7. **Shortlist** the accepted takes with MMR in the content space.
8. **Aggregate**: percentiles, bootstrap interval, stratified drift, diversity.
9. **Gate the run** and build the manifest.

## On-disk contract

One run is one directory. Nothing in the JSON points outside it except by relative
path, so a run can be zipped, moved or archived whole.

```
var/
  runs/
    <run_id>/
      run.json        the complete RunResult, schema version 1
      report.html     self-contained: inlined images, inline SVG, no network
      images/         one frame per plan cell
  comparisons/
    <comparison_id>.json
    <comparison_id>.html
  validation/         frames rendered by `calibrate`, seeds 7000+
suites/
  <suite>.yaml
  references/<character>/     rendered by `bootstrap`, seeds 9000+
```

`run.json` is a pydantic dump of a frozen model tree, so it round-trips exactly:
`load_run(save_run(result)) == result`. The report schema version lives in
`identitylock.REPORT_SCHEMA_VERSION` and in every manifest; it is at 2, and a
version-1 file does not load because the fields it gained cannot be inferred.

## Reproducibility

Every run records what it would take to reproduce it: tool version, report schema
version, Python version, platform, provider name, embedder name and dimension,
suite id, character id, recipe revision, the SHA-256 of every reference image —
and two things it is worth being specific about:

- **the policy itself**, not only its fingerprint. A report has to draw its own
  gate lines, and a consumer that only has a hash ends up reverse-engineering the
  threshold from which candidates were rejected. Three places in this codebase
  did exactly that, and disagreed with each other.
- **the identity space fingerprint.** Adding a character to the cohort, or
  changing an impostor's references, refits the centring and moves every cosine.
  Two runs whose spaces differ are not comparable, and `compare` refuses them.

Every resampling function takes an explicit seed and is deterministic given it. The
synthetic provider is deterministic in `(recipe revision, character, prompt, seed)`,
so a clean checkout and a fresh `make demo` produce byte-identical frames.

## The dashboard

`identitylock serve` mounts a read-only FastAPI over a working directory and serves
a pre-built Vite/React bundle from `src/identitylock/api/static`.

Read-only on purpose. The API never generates, scores or mutates: everything it
serves was produced by the CLI and written to disk. A dashboard that can start a GPU
job is a different product with a different threat model.

The dashboard recomputes nothing — every number it shows is the number stored in
`run.json`, formatted — so it and the static report can never disagree about what a
run measured. The bundle is committed so `pip install identity-lock[api]` works
without a Node toolchain; CI asserts the committed bundle matches its sources.
