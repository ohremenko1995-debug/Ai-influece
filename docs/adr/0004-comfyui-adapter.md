# ADR-0004 — Generation providers behind an adapter; ComfyUI is one implementation

- **Status:** accepted
- **Date:** 2026-08-14
- **Implementation:** scaffold planned for MVP step 6; the interface and configuration
  switch are fixed by this ADR

## Context

Generation runs on ComfyUI today. It will also run on external HTTP APIs (TTS,
lip-sync) and on local `ffmpeg` (montage). ComfyUI's HTTP interface is not a stable
public contract: node names and graph shapes change between versions and between
installations.

Two failure modes must be impossible by construction:

1. **The UI or the API process calling a generation provider directly.** That would
   couple a browser to a GPU host, make jobs unobservable, and put an unbounded
   external call inside a request.
2. **A user prompt becoming workflow JSON.** If arbitrary graph structure can be
   built from user input, a prompt can load a different model, write to a different
   path, or execute a different node — and the "which workflow produced this" question
   becomes unanswerable.

## Decision

All generation goes through one interface, implemented by adapters, and executed
**only** in the ARQ worker.

```python
class GenerationProvider(Protocol):
    async def submit_job(self, payload: GenerationPayload) -> ProviderJob: ...
    async def get_job_status(self, external_job_id: str) -> ProviderJobStatus: ...
    async def cancel_job(self, external_job_id: str) -> None: ...
    async def get_outputs(self, external_job_id: str) -> list[GeneratedOutput]: ...
```

Selected by `GENERATION_PROVIDER`:

| Value | Implementation | Use |
|---|---|---|
| `fake` | `FakeGenerationProvider` | local development, tests, CI — deterministic, no GPU |
| `comfyui` | `ComfyUIProvider` | a reachable ComfyUI instance |

A `Protocol`, not an abstract base class: the adapters share no implementation, and
structural typing keeps the test double free of an inheritance dependency on
production code.

### The workflow is versioned data, not generated structure

`GenerationRecipeVersion` stores the workflow JSON (as a `workflow_file` asset) plus
`workflow_version`, `model_name`, `model_version`, `lora_asset_version_id`,
`prompt_template`, `negative_prompt_template`, `input_schema` and
`default_parameters`.

The worker:

1. loads the **already versioned** workflow JSON,
2. validates runtime inputs against `input_schema`,
3. injects **only** those validated values into designated placeholders,
4. submits.

It never constructs graph structure. A prompt fills a slot; it cannot add a node.
Since the recipe version is immutable ([ADR-0002](0002-versioned-production-assets.md)),
the exact graph used by any historical job is recoverable.

### Output ingestion

For every produced file the worker:

1. downloads it from the provider,
2. computes **SHA-256** over the bytes,
3. uploads to S3/MinIO under a deterministic key,
4. creates `Asset` + `AssetVersion` rows linked to `generation_job_id`,
5. stores the raw provider response on the job for debugging.

The hash is what lets an output be matched back to the bytes that were produced, and
lets a duplicate be recognised instead of re-stored.

### Idempotency

`GenerationJob.idempotency_key` is unique per organization and is also the ARQ job id.
ARQ deduplicates on job id, so a repeated submission is a no-op at the queue layer
*and* at the database layer, rather than a second paid generation. This is the
platform rule "every external side effect must have an idempotency key" made concrete.

### Retry policy

Bounded exponential backoff (`COMFYUI_MAX_RETRIES`, default 3), and a hard
distinction:

| Class | Examples | Retried |
|---|---|---|
| Recoverable | connection refused, timeout, 502/503, queue full, transient OOM | yes, with backoff |
| Non-recoverable | schema validation failure, unknown node, missing model, malformed workflow, 4xx | **no** |

Retrying a validation error cannot succeed. It burns GPU time, delays the operator's
feedback, and hides the real cause behind a timeout.

### Polling, not callbacks

The worker polls `get_job_status`. ComfyUI has no reliable outbound webhook, and a
callback would require the GPU host to reach the API — a network dependency in the
wrong direction. Polling from the worker keeps the GPU host a pure downstream
dependency.

## Consequences

**Gained**

- The entire content pipeline is testable with `FakeGenerationProvider`: no GPU in CI,
  deterministic outputs, and failure modes (timeout, invalid input, cancellation) are
  reproducible on demand.
- Adding a provider is one class plus one enum value.
- ComfyUI version churn is contained in one adapter.
- The UI observes jobs through `GET /generation-jobs/{id}`; it has no knowledge that
  ComfyUI exists.

**Given up**

- Provider-specific features not expressible in the interface need either an
  extension of the interface or `default_parameters` passthrough.
- Polling adds latency versus a push notification, and a small constant load.
- Two implementations to keep behaviourally aligned. Mitigated by testing the
  contract, not the implementation.

## Explicitly out of scope

- Building or editing workflow graphs in the UI. Workflows are authored in ComfyUI and
  uploaded as versioned assets.
- Accepting arbitrary workflow JSON from a request body.
- Any generation call from the API process or the browser.

## Alternatives considered

| Alternative | Why not |
|---|---|
| Call ComfyUI directly from the API | An unbounded external call inside a request; no retry, no cancellation, no progress, and the browser would need reachability to the GPU host. |
| Build workflow JSON from user prompts | Removes the ability to say which workflow produced an output, and turns a prompt field into arbitrary graph execution. |
| Celery instead of ARQ | The stack is async end to end (FastAPI + SQLAlchemy async + asyncpg). ARQ is async-native, so the worker reuses the same services and session handling unchanged. Celery's prefork model would need a sync bridge for every domain call. |
| A dedicated generation microservice | The worker already isolates GPU work in its own process. A separate service would add a network hop and a second source of truth for job state without changing the failure model. |
