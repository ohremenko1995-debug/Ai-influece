# Implementation plan

Eleven stages. Each ends with every quality gate green and its exact results recorded in
[IMPLEMENTATION_STATUS.md](../IMPLEMENTATION_STATUS.md).

Stages 0–8 are the specification's own order. Stages 9 and 10 are beyond it and are recorded
here because both change decisions taken in stages 2–4 — see
[what they mean for the earlier stages](#what-stages-9-and-10-mean-for-stages-24).

Insights comes before conversations deliberately, even though conversations was written down
first. Insights is cheaper, carries no new authority — it only reads — and it feeds the loop
that makes the LLM better. Conversations needs a weaker approval model than anything else in
the product and stores personal data, so it earns its place last.

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

**Post library.** A browsable, searchable view over everything ever drafted, scheduled or
published, per character: filter by platform, account, status, date, content pillar; open the
exact approved snapshot; duplicate a past post as a new publication with its settings
carried over. The data is created by this stage anyway — the library is a read model plus one
action, not a new subsystem, which is why it belongs here and not in a stage of its own.

Two things it must get right:

- **A duplicate starts unapproved.** Copying a published post produces a draft, never an
  inherited approval, because the snapshot hash is about one artefact
  ([ADR-0005](adr/0005-human-approval-before-automatic-publishing.md)).
- **The library is the same table as the history.** A separate "reusable posts" store would
  immediately drift from what was actually published, and then two screens would disagree
  about what the character said.

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

## Stage 9 — Insights: reach, likes, reactions

> **Not designed.** As with stage 10, this states the shape of the problem and the decisions
> already forced by it, not an implementation plan.
>
> It cannot start before stage 5: there is nothing to read metrics from until a real connector
> publishes real posts.

**Goal:** for every post the application published, show what happened to it — reach, views,
likes, reactions, comments, saves — and make that answer a question the user actually has:
which characters, tones, pillars and posting times work.

### The numbers are not comparable, and pretending they are is the main risk

Instagram reach, YouTube views, TikTok views and Telegram channel views are four different
measurements with four different definitions. Adding them produces a number that means
nothing, and a chart that puts them on one axis is a chart that lies.

So the model is:

- **Store platform-native metrics under their platform-native names**, exactly as the platform
  returned them, with the platform's own metric definition version.
- **Derive a small normalised set** — impressions-like, engagement-like, saves-like — and treat
  it as explicitly lossy. Every normalised figure must be able to name what it was derived
  from.
- **Never show a cross-platform total without saying what it sums.** Per-platform panels by
  default; a combined figure only where the underlying metrics genuinely mean the same thing.

Which metric maps to what is platform-specific, so it belongs in the connector manifest and
its schema like every other platform difference
([ADR-0006](adr/0006-social-connector-boundary.md)) — not in a lookup table inside the domain.

### Metrics are a time series, not a value

A post's likes on day 1 and day 30 are different facts, and "is this still growing" is the
more useful one. So `PostMetricSnapshot` is append-only, one row per fetch, carrying
`fetched_at`, the raw platform payload's safe subset, and the normalised view. The current
number is the latest snapshot, not a column that gets overwritten.

This also makes gaps visible, which matters here more than in a server product: a local
scheduler cannot poll while the computer is off, so a week away is a real hole in the series.
**Gaps are shown as gaps.** Nothing is interpolated, and no average silently spans one.

### What actually blocks it — again the platform APIs

Verify at implementation time; these change more than any other endpoints.

| Platform      | Post-level metrics                                                 |
| ------------- | ------------------------------------------------------------------ |
| YouTube       | good — the Analytics API is a genuine reporting surface            |
| Facebook Page | good — Page and post insights                                      |
| Instagram     | good for Professional accounts, and the metric names churn         |
| Threads       | basic insights                                                     |
| VK            | good                                                               |
| X             | own-post metrics, paid tiers                                       |
| TikTok        | limited, and only for authorised business accounts                 |
| Pinterest     | limited                                                            |
| Telegram      | **poor** — the Bot API exposes almost nothing about a channel post |

Telegram being the weakest is awkward, because it is the first connector. That is worth
stating in the UI rather than showing an empty chart: a platform that cannot report is
different from a post that got no reach.

### Reads only, and that is the point

This stage adds no authority. A connector method that fetches insights cannot publish, cannot
change a setting, and cannot approve anything, so it needs no approval model of its own — the
`insights` capability is simply another manifest flag, and `agent` may read metrics like every
other role.

Two constraints do apply:

- **No audience-level data.** Aggregates only. Who liked a post is personal data with no use
  here, so it is not fetched and not stored.
- **Rate limits are the domain's problem**, not something to discover from a 429. Polling
  cadence backs off as a post ages: often on day one, rarely after a month.

### Where it earns its keep

A dashboard of numbers is not the deliverable. The deliverable is the loop back into the
character: which approved examples actually performed, so that the examples fed to
`PersonaPromptService` ([ADR-0007](adr/0007-llm-provider-boundary.md)) are chosen on evidence
rather than on the user's memory of what felt good. That is also the honest limit of it —
correlation over a handful of posts is not proof, and the UI should not imply otherwise.

### Needs an ADR it does not have

Why platform-native metrics are stored verbatim and normalisation is treated as lossy, rather
than defining one canonical "engagement" number up front. The canonical-number design is more
convenient and is the one most analytics products ship; the argument against it — that it
silently equates incomparable measurements — has to be written down before the schema is
fixed, because the schema is what makes it hard to undo.

---

## Stage 10 — Conversations: comments and direct messages

> **Not designed.** This section states the shape of the problem and the decisions that are
> already forced by it. It is not an implementation plan, and it is deliberately not detailed
> to the level of stages 0 and 1 — that happens when the stage begins.
>
> The specification lists automated comment and DM replies as an explicit non-goal **of the
> first version** (§4). Stage 10 does not contradict that: it is post-v1, and it cannot start
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

## What stages 9 and 10 mean for stages 2–4

This is the only reason to record either stage now rather than later. Five things should be
true of the earlier stages' data model, and each is cheap now and expensive to retrofit:

1. **A `PublicationTarget` is the anchor for later facts about a post.** Metrics, and eventually
   comments, attach to the target — one post on one account. A schema that treats a target as a
   transient job record rather than a durable entity makes stage 9 a migration.
2. **Approved examples are a general asset.** A saved good reply is as useful to prompt context
   as a saved good post, and stage 9 wants to rank them by performance — so the examples table
   should be keyed to neither publications nor conversations exclusively.
3. **A character has conversations, not only publications.** `VoiceProfile` and the example set
   are addressed by the publication flow today; nothing should assume that is the only caller.
4. **`ReplyPolicy` will be a versioned approvable artefact.** Whatever generalisation of
   "versioned, append-only, approvable" comes out of stages 2 and 4 should be able to carry a
   third kind of subject without a migration that rewrites it.
5. **Connector capabilities will grow.** `insights` and later `conversations` are new manifest
   flags. Stage 4's capability model should be an open set, not an enum the domain switches on.

Nothing else about stages 9 and 10 should influence earlier work. If either starts driving
decisions beyond these five points, that is scope creep, not foresight.
