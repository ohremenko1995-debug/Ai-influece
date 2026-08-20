# Implementation status

The record of what exists. If a capability is not marked `done` here, it is not implemented,
whatever any other document appears to promise.

**Current state: stage 0 of 9 complete. There is no application code. Nothing runs.**

Last updated: 2026-08-20.

---

## Stages

| Stage | Scope                                                                       | State    |
| ----- | --------------------------------------------------------------------------- | -------- |
| 0     | Repository, donor reference, ported architecture rules, ADR-0001…0011       | **done** |
| 1     | Tauri shell, Next static export, FastAPI sidecar, SQLite, first-run, auth   | next     |
| 2     | Characters, Character Bible versions, Voice Profile versions, disclosure    | planned  |
| 3     | Media library, secure file grants, managed copy, validation                 | planned  |
| 4     | Publication groups and targets, presets, approval snapshots, calendar, jobs | planned  |
| 5     | Real social connectors, Telegram first                                      | planned  |
| 6     | LLM framework and providers                                                 | planned  |
| 7     | Release quality: signed updates, migration safety, diagnostics              | planned  |
| 8     | Cloud extension: media relay, cloud scheduler, sync, team access            | planned  |
| 9     | Conversations: comment and DM replies — beyond the spec, **not designed**   | planned  |

## Stage 0 — delivered

| Item                                                                                        | State |
| ------------------------------------------------------------------------------------------- | ----- |
| Project root and target layout ([README.md](README.md))                                     | done  |
| Contributor rules ([CLAUDE.md](CLAUDE.md))                                                  | done  |
| Donor reference ([docs/donor-reference.md](docs/donor-reference.md))                        | done  |
| Architecture ([docs/architecture.md](docs/architecture.md))                                 | done  |
| Security and privacy policy ([docs/security.md](docs/security.md))                          | done  |
| ADR-0001 … ADR-0011 ([docs/adr/](docs/adr/))                                                | done  |
| Implementation plan ([docs/implementation-plan.md](docs/implementation-plan.md))            | done  |
| Repository extraction note ([docs/repository-extraction.md](docs/repository-extraction.md)) | done  |

### Gates run for stage 0

Stage 0 is documentation, so only the formatting gate applies. Everything else has no subject
yet, and reporting a pass for a gate with nothing to check would be false.

| Gate                                           | Result                                           |
| ---------------------------------------------- | ------------------------------------------------ |
| `prettier --check` over the new markdown       | pass — 20 files match                            |
| Internal markdown links resolve                | pass — 123 relative links and 1 anchor, 0 broken |
| `ruff` / `mypy` / `pytest`                     | not run — no Python exists                       |
| `eslint` / `tsc` / `vitest` / `next build`     | not run — no TypeScript exists                   |
| `cargo fmt` / `clippy` / `test`                | not run — no Rust exists                         |
| sidecar startup, API smoke, fake connector E2E | not run — nothing to start                       |

---

## Not implemented

Everything below is specified and decided, and none of it exists. Listed explicitly because a
reader who has just finished the ADRs could reasonably assume otherwise.

**Application shell**

- Tauri shell, tray, single-instance lock, notifications, file picker, file grants
- The sidecar, the startup handshake, the API proxy, `api_request`
- Any Tauri command
- First-run wizard, data root selection, portable and installed modes
- Signed updater, `latest.json`, migration backup and recovery

**Backend**

- Every route. `/api/v1` does not exist.
- SQLite schema, Alembic revisions, the type decorators
- Auth, roles, the permission matrix, the agent fence
- Characters, Character Bible versions, Voice Profile versions, disclosure policies
- Media library, import, hashing, thumbnails, validation engine, ffprobe bundling
- Publication groups and targets, presets, approval decisions, snapshot hashing
- The scheduler, the job table, leases, idempotency keys, late-publish recovery
- Every social connector, including `FakeSocialConnector`
- Every LLM provider, including `FakeLLMProvider`, and `PersonaPromptService`
- Audit log
- Media relay and cloud scheduler implementations

**Frontend**

- Every screen, including login
- `ApiTransport` and its implementations
- i18n scaffolding, Russian or English
- Generated OpenAPI types

**Known open questions**

- How the future cloud scheduler obtains publishing credentials — delegated tokens or an auth
  relay — is unresolved and deliberately left to its own ADR at stage 8
  ([ADR-0010](docs/adr/0010-optional-media-relay-and-cloud-scheduler.md)).
- Whether a change to a scheduled time voids an approval is a workspace policy with a default,
  not a fixed rule ([ADR-0005](docs/adr/0005-human-approval-before-automatic-publishing.md)).
- This project currently lives as a subtree of the donor repository rather than in its own
  repository ([docs/repository-extraction.md](docs/repository-extraction.md)).
- Stage 9 (comment and DM replies) is recorded in the plan but **not designed**. It needs two
  ADRs that do not exist: one arguing why a human-approved _policy_ is an acceptable substitute
  for a per-artefact snapshot approval, and one on conversation logs as personal data —
  retention, deletion on request, and what may be sent to an LLM provider
  ([docs/implementation-plan.md](docs/implementation-plan.md)).

---

## How to update this file

After each stage: add the stage's delivered items with their state, paste the **exact** gate
output — not a summary of it — and move anything that turned out to be untrue out of the
delivered list. A gate that was not run is recorded as not run, with the reason.
