# Implementation plan

Ten stages. Each ends with every quality gate green and its exact results recorded in
[IMPLEMENTATION_STATUS.md](../IMPLEMENTATION_STATUS.md).

Stages 0–8 are the specification's own order. Stage 9 is beyond it, recorded here because
it changes decisions taken in stages 2–4 — see [its own note](#what-stage-9-means-for-stages-24).

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

---

## Stage 9 — Conversations: comments and direct messages

> **Not designed.** This section states the shape of the problem and the decisions that are
> already forced by it. It is not an implementation plan, and it is deliberately not detailed
> to the level of stages 0 and 1 — that happens when the stage begins.
>
> The specification lists automated comment and DM replies as an explicit non-goal **of the
> first version** (§4). Stage 9 does not contradict that: it is post-v1, and it cannot start
> before stages 5, 6 and 8 exist.

**Goal:** the character answers comments and direct messages in its own voice, at a volume no
person could handle by hand, without any single reply being something a human would not have
sanctioned.

### The line this stage holds

Two requirements are easy to conflate, and only one of them is in scope.

| In scope                                                                                                                                                        | Not in scope, ever                                                            |
| --------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------- |
| Replies that read as natural language rather than a bot template — real reaction to the specific message, memory of the conversation, the character's own voice | Replies designed to make the other person believe they are talking to a human |

The first is what `VoiceProfile` already exists for: sentence length, emoji rules, favourite
and forbidden expressions, how the audience is addressed. There is no reason to hold back on
it, and doing it well is most of the product value here.

The second is out of scope for four independent reasons, any one of which would be sufficient:

- The project's transparency rule. Characters are openly virtual, and no feature may exist to
  hide that content is synthetic or to impersonate a real person
  ([ADR-0011](adr/0011-no-media-generation.md), [security.md](security.md)).
- Regulation. Where the audience is in the EU, the AI Act's transparency obligations require a
  person to be informed they are interacting with an AI system. Applicable since August 2026;
  the specifics belong with a lawyer, but the direction is not ambiguous.
- Platform terms. Every platform in scope requires an automated account to be identifiable and
  prohibits impersonation. A ban is not a hypothetical consequence.
- Asymmetry. One screenshot captioned "I thought this was a real person" costs more than
  concealment could ever earn, and audiences engage with declared brand personas anyway.

In practice: disclosure lives in the profile and bio, not in every reply; the character never
claims to be human, and answers honestly if asked directly. Everything else is free.

### What actually blocks it — the platform APIs, not the LLM

Programmatic conversation access is far worse than publication access, and it varies more.
Verify all of this against current documentation when the stage starts; these APIs change more
often than any others in the product.

| Platform      | Comments                       | Direct messages                        |
| ------------- | ------------------------------ | -------------------------------------- |
| Telegram      | yes, Bot API, no vendor review | yes, straightforward                   |
| Facebook Page | yes, Graph API                 | yes, Messenger Platform                |
| Instagram     | yes, Professional accounts     | yes, but a messaging window and review |
| YouTube       | yes, tight quotas              | no such feature                        |
| Threads       | limited                        | no                                     |
| X             | yes, paid tiers                | yes, paid tiers                        |
| VK            | yes                            | yes, via a community                   |
| TikTok        | effectively no                 | no                                     |
| Pinterest     | almost none                    | no                                     |

Realistically that is Telegram, the Meta group and YouTube — and Telegram first again,
because a bot token needs no review.

### The hard part is the approval gate, not the generation

Approving every individual reply by hand does not survive contact with volume. Not approving
them means a machine speaks for the brand. The way out is to move the human decision one level
up:

**A person approves a policy, not a reply.** `ReplyPolicy` is a versioned append-only artefact,
exactly like the Character Bible: permitted topics, tone, prohibitions, what to do with an
unknown question, a daily message ceiling. The machine may only act strictly inside a policy
that currently holds a human approval. This is the same structure as
[ADR-0005](adr/0005-human-approval-before-automatic-publishing.md) — the `agent` role still
cannot approve anything, it can only execute a decision a person already made — and it will
need its own ADR, because a policy authorises a _class_ of future messages rather than one
exact artefact, which is a genuinely weaker guarantee than a snapshot hash and has to be
argued for on its own terms.

Three tiers, with the boundary drawn by classification rather than by keyword lists alone:

| Tier                            | When                                                        |
| ------------------------------- | ----------------------------------------------------------- |
| auto-reply                      | classified low risk, squarely inside the active policy      |
| draft queued for a human        | anything ambiguous — the LLM prepares it, a person sends it |
| hard escalation, no draft shown | the categories below                                        |

Hard escalation, unconditionally: money and payments, health, legal questions, any signal that
the other party may be a minor, personal data, complaints, hostility, and anything reading as a
crisis. These do not get a suggested reply, because a suggested reply is something a tired
person clicks past.

### Invariants reused unchanged

- An idempotency key per inbound message, so a reply can never be sent twice — the same
  mechanism as publishing.
- The audit row and the state change in one transaction.
- A connector boundary: `ConversationConnector` alongside `SocialConnector`
  ([ADR-0006](adr/0006-social-connector-boundary.md)), so no platform's inbox model reaches the
  domain.
- A kill switch that stops every automatic reply in one action, for every character and
  account at once.
- Rate ceilings per account per day, enforced in the domain rather than discovered from a
  platform's 429.

### One genuinely new concern

**A conversation log is personal data.** Not "another table": it needs a retention period, a
deletion path that works on request, encryption at rest, a decision about what may be sent to
an LLM provider and what may not, and a defensible answer to why any of it is stored at all.
That is its own ADR, and it is the part of this stage most likely to be underestimated.

### Prerequisites

Stage 5 (a working connector), stage 6 (`PersonaPromptService`), and stage 8 — inbound messages
arrive while the computer is off, so a purely local loop hits exactly the wall that scheduled
publishing does.

### What stage 9 means for stages 2–4

This is the only reason to record the stage now rather than later. Three things should be true
of the earlier stages' data model, and each is cheap now and expensive to retrofit:

1. **A character has conversations, not only publications.** `VoiceProfile` and the approved-example
   set are addressed by the publication flow today; nothing should assume that is the only caller.
2. **Approved examples are a general asset.** A saved good reply is as useful to prompt context as
   a saved good post, so the examples table should not be keyed to publications.
3. **`ReplyPolicy` will be a versioned approvable artefact.** Whatever generalisation of
   "versioned, append-only, approvable" comes out of stages 2 and 4 should be able to carry a
   third kind of subject without a migration that rewrites it.

Nothing else about stage 9 should influence earlier work. If it starts driving decisions beyond
these three points, that is scope creep, not foresight.
