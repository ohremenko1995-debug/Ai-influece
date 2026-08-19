# Donor reference

InfluencerOS Desktop is not a fresh start. The web MVP one level up — an InfluencerOS
control centre with organizations, RBAC, a character registry, append-only Character
Bible versions and a transactional audit log — is the architecture donor. This document
records exactly what is inherited, where the original lives, and what is deliberately
left behind.

Donor paths are written relative to the donor repository root, which is `../../` from
this file. They are reading references, not dependencies: **no code in this project
imports the donor.** Ported code is copied and adapted, and once it diverges the copy is
authoritative.

Donor state at the fork: MVP steps 1–2, commit `5fd41d8`, 199 backend tests and 52
frontend tests green.

---

## Inherited — backend

| Concern                                  | Donor source                                        | How it changes here                                                                    |
| ---------------------------------------- | --------------------------------------------------- | -------------------------------------------------------------------------------------- |
| Modular monolith layout                  | `apps/api/app/{api,core,modules,shared}`            | same shape, at `apps/local-api/app/…`                                                  |
| `router → service → repository → models` | every `app/modules/*/`                              | unchanged                                                                              |
| Single error envelope                    | `app/core/errors.py`, `app/main.py`                 | same shape; codes must be stable because the desktop UI localises from them            |
| Request ID + structured logging          | `app/shared/observability/`                         | keep the lazy logger and `plain_traceback`; output goes to `<DATA_ROOT>/logs`          |
| `Organization`, `User`, `Membership`     | `app/modules/{organizations,users}/models.py`       | unchanged; one local organization, created by the first-run wizard                     |
| Email/password auth, Argon2id            | `app/core/security.py`, `app/modules/auth/`         | same hashing; the refresh session may be kept in Credential Manager                    |
| Permission-based RBAC + agent fence      | `app/shared/permissions/`                           | same mechanism, extended with media, social, publication, LLM and settings permissions |
| Tenant scoping, 404 on cross-tenant      | `app/shared/db/base.py` (`OrganizationScopedMixin`) | unchanged, kept even in single-user local mode                                         |
| Character registry                       | `app/modules/influencers/`                          | table stays `influencers`; the UI term becomes «Персонаж» / Character                  |
| Append-only version tables               | `app/modules/character_versions/`                   | pattern reused verbatim for `VoiceProfileVersion`                                      |
| Disclosure policies                      | `app/modules/influencers/models.py`                 | unchanged; disclosure text becomes part of the approval snapshot hash                  |
| Audit log with before/after              | `app/modules/audit/`                                | `sequence_number` ordering kept; the audited action list grows considerably            |
| "Services never commit"                  | `app/shared/db/session.py`                          | unchanged                                                                              |
| Generic state machine                    | `app/core/state_machine.py`                         | reused for `MediaAsset`, `PublicationTarget` and `PublicationGroup`                    |
| Acting identity                          | `app/core/actor.py`                                 | `CurrentActor` unchanged; the scheduler runs as the system actor                       |
| Sequential migration names               | `apps/api/alembic/`                                 | same convention; SQLite needs batch operations for most `ALTER`s                       |
| ARQ worker packaging lesson              | `apps/worker/worker/main.py`                        | the scheduler replaces ARQ, but the "register nothing fake" rule carries over          |

## Inherited — frontend

| Concern                      | Donor source                                                | How it changes here                                               |
| ---------------------------- | ----------------------------------------------------------- | ----------------------------------------------------------------- |
| Types generated from OpenAPI | `packages/types`, `make openapi`                            | unchanged                                                         |
| Enum drift guard             | `apps/web/src/lib/contract.test.ts`                         | reused; this UI has many more enums to keep honest                |
| Single API boundary          | `apps/web/src/lib/api-client.ts`                            | becomes `ApiTransport` over Tauri IPC, not `fetch` against a port |
| Session store                | `apps/web/src/lib/auth-store.ts`                            | same shape; the refresh token moves to Credential Manager         |
| UI primitives and layout     | `packages/ui`, `apps/web/src/components`                    | reused; every string moves behind an i18n key                     |
| Confirm dialog pattern       | `apps/web/src/components/confirm-dialog.tsx`                | reused for archive, disconnect, physical delete and relay consent |
| Version viewer pattern       | `apps/web/src/features/influencers/character-bible-tab.tsx` | reused for Voice Profile versions and approval snapshots          |
| Tailwind v4 token theme      | `apps/web/src/app/globals.css`                              | reused; status tones extend to media and publication statuses     |

---

## The four donor rules

| Donor rule                                                                                                                                 | Status here                                                                              |
| ------------------------------------------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------- |
| The UI never talks to a generation provider ([donor ADR-0004](../../docs/adr/0004-comfyui-adapter.md))                                     | **Moot.** There is no generation provider. ([ADR-0011](adr/0011-no-media-generation.md)) |
| Identity, recipes and prompts are versioned, not edited ([donor ADR-0002](../../docs/adr/0002-versioned-production-assets.md))             | **Kept**, narrowed to identity: Character Bible and Voice Profile                        |
| Scheduling requires a recorded human approval; no autonomous publishing ([donor ADR-0003](../../docs/adr/0003-human-approval-gate.md))     | **Superseded** by [ADR-0005](adr/0005-human-approval-before-automatic-publishing.md)     |
| Every consequential change writes an audit row in the same transaction ([donor ADR-0007](../../docs/adr/0007-audit-log-in-transaction.md)) | **Kept**, unchanged                                                                      |

The supersession is the only substantive rule change in the fork, and it is narrow:

> Automatic publishing is allowed only for a specific platform version that holds a
> valid human approval. Any change to the file, text, disclosure, account, time or
> platform settings voids that approval.

The donor forbade automatic publishing outright because it had nothing to bind a
decision to: an approval there covered "this content item", and the content item could
still change afterwards. This project computes a snapshot hash over everything that
determines what the audience will see, so a decision can be bound to one exact artefact.
That is what makes delegation to a scheduler different from delegation to a machine — the
person still decides, and the scheduler is only allowed to execute a decision that is
provably still about the same thing.

Also inherited as documents rather than code: the donor's
[architecture](../../docs/architecture.md), [domain model](../../docs/domain-model.md) and
[security](../../docs/security.md) notes, and
[donor ADR-0005](../../docs/adr/0005-rbac-permission-model.md), which remains the
reference for the permission model and the agent fence.

---

## Not inherited

Dropped as runtime requirements, because a desktop user installs one signed installer and
nothing else ([ADR-0001](adr/0001-desktop-local-first.md)):

| Donor component     | Replacement here                                                                                                     |
| ------------------- | -------------------------------------------------------------------------------------------------------------------- |
| PostgreSQL          | SQLite with WAL and foreign keys ([ADR-0003](adr/0003-sqlite-local-postgresql-cloud.md))                             |
| Redis + ARQ         | a database-backed scheduler with lease and lock ([ADR-0005](adr/0005-human-approval-before-automatic-publishing.md)) |
| MinIO / S3          | `LocalFilesystemStorage` over a managed library ([ADR-0004](adr/0004-managed-local-media-library.md))                |
| Docker Compose      | a Tauri-supervised sidecar process ([ADR-0002](adr/0002-fastapi-sidecar-inside-tauri.md))                            |
| `apps/worker` (ARQ) | the scheduler loop inside the sidecar                                                                                |

Dropped as product scope ([ADR-0011](adr/0011-no-media-generation.md)):

- the ComfyUI adapter and the whole generation-job pipeline
- LoRA, workflow and recipe versioning
- asset provenance: prompts, models, seeds, generation lineage
- QA review of generated frames and identity-drift scoring
- the donor's planned steps 3–8 (asset library as generation output, recipes, content
  factory, generation jobs, QA, experiments)

Deliberately **not** carried over, even though it would have been convenient:

| Donor artefact                                                                             | Why not                                                                                                                                                                                           |
| ------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| The development auth stub ([donor ADR-0006](../../docs/adr/0006-development-auth-stub.md)) | A desktop build ships to end users. An authentication bypass guarded by an environment variable is a liability on a machine we do not control. Tests construct a `CurrentActor` directly instead. |
| `app/shared/queue/redis.py`                                                                | Nothing in this product may require a broker.                                                                                                                                                     |
| `app/shared/storage/s3.py`                                                                 | The media relay is the only remote storage, it is opt-in, and it is a connector.                                                                                                                  |
| Stateless-only JWTs                                                                        | The app can lock and unlock from the tray, so a local session table earns its keep here in a way it did not in the donor.                                                                         |
