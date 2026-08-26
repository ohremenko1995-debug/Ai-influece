# seedance-gateway

A cost-aware gateway for **ByteDance Seedance 2.5** video generation: one job
contract, several provider adapters, a spend ledger that can stop a run, and a
draft-then-final workflow that exists purely to make each finished clip cheaper.

Standalone by design — its own `pyproject.toml`, tests and README — so it can be
lifted into its own repository with a `git subtree split`. It shares the Python
version, the ruff rule set and the module layout of `apps/api`, so it can equally
well be folded into InfluencerOS later.

---

## Why this exists

Seedance bills on the video it produces:

```
tokens = (input video seconds + output seconds) x width x height x fps / 1024
```

Three consequences drive the whole design:

| Lever | Effect |
| --- | --- |
| Resolution | 480p → 720p is **2.25x** for identical footage; 720p → 1080p another **2.5x** |
| Duration | strictly linear — a 30 s clip costs exactly six 5 s clips |
| Inputs | prompt, first frame and reference images are **free**; so is audio |
| Video input | moves the job to a cheaper token rate ($6.40/M vs $10.70/M direct) |

So the saving is not in finding a cheaper reseller — the spread between the
cheapest and dearest route is about 2x, while iterating at 480p instead of 720p
is 2.25x on every discarded take. Three 480p drafts plus one 720p final costs
**~$2.70** per finished 5-second clip. Four takes straight to 720p: **$4.62**.

The gateway makes that the default path and refuses to let a run drift past a
budget while you are not looking.

## Quick start

```bash
uv venv .venv --python 3.11
uv pip install --python .venv/bin/python -e '.[dev]'
source .venv/bin/activate

cp .env.example .env          # then put a key in it
seedance rates                # what a 5 s 720p clip costs everywhere
seedance draft "your prompt" -n 3 --provider fake   # end to end, no key, no bill
```

Nothing is sent until a provider key is set; `--provider fake` runs the entire
pipeline offline against a placeholder file.

## The pipeline

```bash
seedance budget --daily 20 --monthly 300     # a cap that actually blocks
seedance draft "a cinematic slow push-in ..." -n 3    # 3 seeds at 480p
seedance final --pick 2                              # that seed at 720p
seedance spend                                       # what went out
```

`draft` fans out one spec per seed. `final` takes the seed you picked and
re-runs it at final resolution — same prompt, same seed, so what you approved is
what you get. Every command prints the cost before it spends it, and
`--dry-run` prints the exact HTTP request instead of sending it.

## Commands

| Command | What it does |
| --- | --- |
| `seedance rates` | Price one clip across every provider in the table |
| `seedance estimate` | Cost a specific job without submitting it |
| `seedance draft` | Cheap takes, one per seed |
| `seedance final` | Promote one draft to final resolution |
| `seedance jobs` / `run` | What was generated, at what cost |
| `seedance spend` / `budget` | Committed spend, and the caps that block a run |
| `seedance providers` | Which adapters have credentials |

## Providers

Adapters exist for the three routes worth calling; the rest of `rates.toml` is
priced for comparison only.

| Adapter | Why it is here |
| --- | --- |
| `modelark` | BytePlus ModelArk, ByteDance's own international channel. Cheapest non-promo rate, and the only one that returns `usage.completion_tokens` — the authoritative charge |
| `replicate` | Same price as direct at 480p/720p, takes a card without a BytePlus account |
| `wavespeed_turbo` | Cheapest published 720p rate. A different model, not a discount on the same one |
| `wavespeed` | Standard variant of the above |
| `fake` | Offline; generates a placeholder so the pipeline can be tested without a bill |

### Before the first paid call

Network egress was restricted while this was written, so the price table and the
wire formats come from published documentation and provider pages rather than
from live calls. Both are pinned in one place each and both need one check:

1. `seedance draft "test" --provider <name> --dry-run` prints the exact request.
   Compare it against the provider's current docs and curl it once.
2. `seedance rates` prints each price with the date it was read. Re-read the
   provider console and update `rates.toml` before committing to volume.

The estimator refuses to price a resolution it has no published number for
rather than guessing — a missing rate is an error at submit time, not a surprise
on the invoice.

## Configuration

`.env` or the environment. Credentials keep the names the providers document
(`ARK_API_KEY`, `REPLICATE_API_TOKEN`, `WAVESPEED_API_KEY`); everything else is
prefixed `SEEDANCE_`. See `.env.example`.

## Development

```bash
make check     # ruff + mypy --strict + pytest
```

The test suite runs fully offline: provider adapters are asserted against
recorded payloads via `respx`, and the pipeline runs end to end on the `fake`
provider. `tests/test_pricing.py` pins the token formula to ByteDance's own
published examples — 5 s of 16:9 at $0.514 / $1.156 / $2.843 — so a wrong
divisor or frame size fails the build rather than the budget.
