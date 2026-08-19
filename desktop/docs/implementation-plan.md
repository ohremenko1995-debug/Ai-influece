# Implementation plan

Nine stages. Each ends with every quality gate green and its exact results recorded in
[IMPLEMENTATION_STATUS.md](../IMPLEMENTATION_STATUS.md).

Two rules govern this document:

- **A short plan and a module list are written before each stage begins**, not after. Stage 0
  and stage 1 are planned to that level below; later stages are stated at the level the spec
  fixes them, and are expanded when their turn comes. Planning stage 6 in detail today would
  be speculation dressed as a plan.
- **This file is updated after each stage**, together with the status file.

---

## Stage 0 — Repository, rules and decisions ✅

**Goal:** somewhere to put stage 1, with the decisions already made and written down.

| Deliverable                                       | File                                                    |
| ------------------------------------------------- | ------------------------------------------------------- |
| Project root, target layout, status legend        | [README.md](../README.md)                               |
| Rules for anyone changing this code               | [CLAUDE.md](../CLAUDE.md)                               |
| What is inherited from the donor and what is not  | [donor-reference.md](donor-reference.md)                |
| Ported architectural rules, desktop process model | [architecture.md](architecture.md)                      |
| Secrets, privacy, audit, transparency policy      | [security.md](security.md)                              |
| Eleven decisions                                  | [adr/0001–0011](adr/)                                   |
| How the subtree becomes its own repository        | [repository-extraction.md](repository-extraction.md)    |
| The record of what exists                         | [IMPLEMENTATION_STATUS.md](../IMPLEMENTATION_STATUS.md) |

**Deliberately not done:** no `apps/`, no `packages/`, no `pnpm-workspace.yaml`, no
`justfile`. An empty package is not a deliverable, and git does not track empty directories.
Stage 1 creates them with code in them.

**Gates:** documentation only, so the applicable gate is `prettier --check` over the markdown.
Recorded in the status file.

---

## Stage 1 — Desktop foundation

**Goal:** a signed installer that installs on a clean Windows machine, starts, asks the
first-run questions, creates a database, and lets one owner log in. Nothing domain-specific.

**Modules created**

| Module                                                               | Contents                                                                                                                                                                                                               |
| -------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `apps/desktop-shell/src-tauri/`                                      | Tauri app, single-instance lock, tray, sidecar supervisor, API proxy                                                                                                                                                   |
| `apps/desktop-shell/src-tauri/commands/`                             | `api_request`, `select_data_root`, `select_import_files`, secret commands, updater commands, `app_lock`, `app_quit`, `app_relaunch`, `tray_set_status`, `notification_show`, `reveal_in_explorer`, `open_external_url` |
| `apps/desktop-shell/binaries/`                                       | bundled sidecar executable and `ffprobe.exe`                                                                                                                                                                           |
| `apps/local-api/app/core/`                                           | settings, errors, security, state machine, acting identity                                                                                                                                                             |
| `apps/local-api/app/api/`                                            | dependencies, `/api/v1` router, readiness                                                                                                                                                                              |
| `apps/local-api/app/shared/db/`                                      | engine with WAL and `foreign_keys=ON`, session unit of work, type decorators                                                                                                                                           |
| `apps/local-api/app/shared/permissions/`                             | permission enum, role matrix, agent fence                                                                                                                                                                              |
| `apps/local-api/app/shared/observability/`                           | request id middleware, structured logging into `<DATA_ROOT>/logs`                                                                                                                                                      |
| `apps/local-api/app/modules/organizations`, `users`, `auth`, `audit` | ported from the donor                                                                                                                                                                                                  |
| `apps/local-api/app/modules/setup/`                                  | first-run wizard: data root validation, database creation, first owner                                                                                                                                                 |
| `apps/local-api/alembic/`                                            | `0001_initial_schema` with batch operations                                                                                                                                                                            |
| `apps/desktop-ui/`                                                   | Next.js static export, `ApiTransport` + `DesktopLocalTransport` + `MockTransport`, i18n scaffold (ru filled, en keys), login, first-run wizard, shell chrome                                                           |
| `packages/{ui,types,config}`                                         | ported primitives, generated OpenAPI types, shared lint/tsconfig bases                                                                                                                                                 |
| `tools/build-sidecar/`                                               | sidecar build for CI                                                                                                                                                                                                   |

**Order within the stage**

1. Sidecar that boots, reads settings, opens SQLite, answers a readiness route.
2. Tauri shell that starts it, performs the handshake, proxies `api_request`.
3. Alembic `0001` plus the upgrade/downgrade/upgrade test.
4. Auth: Argon2id, login, refresh, session.
5. First-run wizard, end to end, including the refusal to write into `Program Files`.
6. Tray, lock, quit, notifications.
7. Static export wired to the real transport.
8. Updater skeleton with signature verification, no release yet.
9. Windows installer CI job with an install smoke test.

**Done when:** a clean Windows VM installs the app, the wizard completes, an owner logs in
after a restart, closing the window leaves it in the tray, quitting from the tray stops the
sidecar, and the installer smoke test passes in CI.

**Risks:** bundling Python so it starts fast enough not to feel broken; a first-run wizard that
must handle a read-only or full disk; signing configuration in CI without the key ever
touching the repository.

---

## Stage 2 — Characters and Voice Profile

Port the influencer registry, Character Bible versions, disclosure policy. Add
`VoiceProfile` + append-only `VoiceProfileVersion`. Audit tabs. The character screens.
Every version edit creates a version; nothing is edited in place.

## Stage 3 — Media library and validation

Secure file grants from the Rust picker. Managed copy with SHA-256 and atomic rename.
Thumbnails. Image metadata via Pillow, video metadata via bundled `ffprobe.exe`. Platform
rulesets. The critical/warning flow with audited acknowledgement. Manual checklist. Archive,
and physical deletion as a separate confirmed operation.

## Stage 4 — Publication domain

`PublicationGroup` and `PublicationTarget`. Presets. Approval snapshots and hash
invalidation. Calendar. The persistent job table with lease and idempotency key.
`FakeSocialConnector`. A complete local end-to-end publication flow with no external
platform involved — this is the flow that becomes a release gate.

## Stage 5 — First real social connector

Telegram first, because a bot token needs no vendor review, so the whole path can be proven
against a real platform. Then YouTube, the Meta group (Instagram, Facebook, Threads), TikTok,
Pinterest, X, VK. Each passes its own contract test suite. A connector awaiting vendor review
stays `requires_review` and is not offered as working.

## Stage 6 — LLM framework

`PersonaPromptService`. `FakeLLMProvider`, then OpenAI, Anthropic and the custom
OpenAI-compatible adapter, then Gemini and Mistral. 1–5 variants, default 5. Feedback and
approved examples. Optional vision, off by default.

## Stage 7 — Release quality

The update flow through GitHub Releases. Migration backup and rollback. The code-signing
pipeline. Diagnostics bundle. Opt-in crash reporting. A clean Windows install test and an
upgrade-from-previous-stable test.

## Stage 8 — Cloud extension

`MediaRelayConnector` implementation. Auth relay if required. `CloudSchedulerConnector`
implementation. Local/cloud sync policy and conflict resolution. Team access. Commercial
licensing and billing are a separate project.
