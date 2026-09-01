# Running against a real ComfyUI box

> The adapter is written against ComfyUI's documented HTTP API and is **not
> exercised in this repository's CI** — the test container has no GPU and no
> ComfyUI host, and a green test against a mock would only prove the mock works.
> Its placeholder substitution and output selection are unit-tested; the HTTP paths
> are not.

## The contract

Export your graph with **Save (API Format)**, then replace the widget values you
want the harness to drive with placeholders:

| Placeholder      | Becomes                                                    |
| ---------------- | ---------------------------------------------------------- |
| `{{prompt}}`     | `prompt_prefix + the cell's prompt + prompt_suffix`        |
| `{{negative}}`   | the recipe's `negative_prompt`                             |
| `{{seed}}`       | the cell's seed, as an integer                             |
| `{{width}}` `{{height}}` `{{steps}}` `{{cfg}}` | from the recipe             |
| `{{sampler}}` `{{scheduler}}` `{{model}}`      | from the recipe             |
| `{{character}}`  | the character id, for a trigger word                       |

A placeholder that occupies the whole string becomes a **typed** value, so
`"seed": "{{seed}}"` reaches ComfyUI as an integer. One embedded in a longer string
is interpolated as text: `"text": "photo of {{character}}, {{prompt}}"`. Anything
the template does not reference is left exactly as you saved it — the adapter never
invents graph structure.

Top-level keys starting with `_` are treated as comments and dropped before the
graph is submitted — the API format has nowhere else to write down what a template
is for. [`suites/workflows/portrait.api.json`](../suites/workflows/portrait.api.json)
is a working example built from stock nodes.

**Keep exactly one SaveImage node.** A graph that saves from several nodes is
rejected rather than guessed at: the scored frame must be unambiguous.

## Running

```bash
identitylock run \
  --suite suites/mine.yaml \
  --recipe krea2-lora-v3 \
  --provider comfyui \
  --comfyui http://comfyui.local:8188 \
  --workflow suites/workflows/krea2-portrait.api.json \
  --gate
```

The adapter submits to `POST /prompt`, polls `GET /history/{prompt_id}` until
outputs appear, and fetches the frame from `GET /view`. Default timeout is 600 s per
cell; an execution error in the history is raised, never retried silently.

## The recipe side

Recipe fields are what the run is *labelled* with and what the revision hashes over,
so keep them truthful — the harness has no way to know your workflow actually used
28 steps if the recipe says 8.

```yaml
recipes:
  krea2-lora-v3:
    name: Krea 2 Turbo + identity LoRA v3
    provider: comfyui
    model: krea2_turbo_fp8
    sampler: er_sde
    scheduler: simple
    steps: 8
    cfg: 1.0
    width: 1920
    height: 1080
    loras:
      - name: ava-identity-v3
        weight: 0.85
    prompt_prefix: "raw photograph of ava, "
    prompt_suffix: ", 85mm f/1.4, natural skin texture, visible pores"
```

Changing any of those produces a new revision, and a comparison between two runs on
the *same* revision is refused — there would be nothing to compare.

## Two frugal alternatives

**Generate first, score after.** Often the better shape: keep generation in whatever
tooling you already have, dump frames named `<character>.<prompt>.<seed>.png` into a
folder, and point the directory provider at it.

```bash
identitylock run --suite suites/mine.yaml --recipe v3 \
  --provider directory --images ./renders --gate
```

**Score a live box once, then iterate offline.** Run against ComfyUI once to fill
`var/runs/<id>/images`, then re-score those frames with different policies or
embedders as often as you like — scoring never touches the GPU.
