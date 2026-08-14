# InfluencerOS

Internal control center for creating and governing photorealistic **AI influencers**:
character identity, versioned production recipes, generation jobs, QA, human
approval and content scheduling.

InfluencerOS treats its characters as **openly virtual personas**. Every influencer
carries a disclosure policy, activation is blocked until an adult-representation
confirmation and a Character Bible exist, and content cannot reach a publication
surface without a recorded human approval. The platform has no features for hiding
the synthetic nature of content, impersonating real people, or cloning a voice
without a recorded commercial-use confirmation.

---

## Status

MVP **step 1 and step 2** are implemented and verified. Later steps are scoped but
not built — see [Roadmap](#roadmap).

| Area                                                                                              | State                                                                          |
| ------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------ |
| Docker Compose stack (postgres, redis, minio, api, worker, web)                                   | authored, **not executed in CI** (see [Known limitations](#known-limitations)) |
| FastAPI app, config, structured logging, error envelope, health probes                            | done                                                                           |
| Schema: Organization, User, Membership, DisclosurePolicy, Influencer, InfluencerVersion, AuditLog | done, migration `0001`                                                         |
| Auth: password login, refresh, development stub                                                   | done                                                                           |
| RBAC: 7 roles, 43 permissions, agent fence                                                        | done                                                                           |
| Influencer registry + lifecycle state machine                                                     | done                                                                           |
| Character Bible versioning (append-only)                                                          | done                                                                           |
| Audit log with before/after diffs                                                                 | done                                                                           |
| Web app shell: login, dashboard, influencer list/detail                                           | done                                                                           |
| Assets, recipes, content factory, generation jobs, QA, approvals, calendar                        | **not started**                                                                |

Quality gates, all green:

| Gate                  | Result                                                                |
| --------------------- | --------------------------------------------------------------------- |
| `ruff check`          | All checks passed                                                     |
| `ruff format --check` | 90 files already formatted                                            |
| `mypy --strict`       | no issues found in 89 source files                                    |
| `pytest`              | **194 passed**                                                        |
| `tsc --noEmit`        | 3 packages, no errors                                                 |
| `eslint`              | 0 errors (1 informational React Compiler notice about TanStack Table) |
| `prettier --check`    | all files match                                                       |
| `vitest`              | **52 passed**                                                         |
| `next build`          | compiled, 7 routes                                                    |

Backend tests run against a real PostgreSQL 16 database and build the schema by
running the Alembic migrations, so every run also proves the migrations apply and
reverse. The web app was additionally driven in a real browser against the running
API — login, dashboard, influencer list, all four detail tabs, Character Bible
versions and the audit trail.

---

## Quick start

```bash
make env          # create .env from .env.example
make up           # build and start the whole stack
make migrate      # apply migrations
make seed         # create a dev organization and one user per role
```

Then open:

| Service       | URL                        |
| ------------- | -------------------------- |
| Web app       | http://localhost:3000      |
| API docs      | http://localhost:8000/docs |
| MinIO console | http://localhost:9001      |

Seeded development logins (password `influenceros`):

| Role          | Email                               |
| ------------- | ----------------------------------- |
| owner         | owner@influenceros.example.com      |
| creative_lead | creative@influenceros.example.com   |
| operator      | operator@influenceros.example.com   |
| reviewer      | reviewer@influenceros.example.com   |
| compliance    | compliance@influenceros.example.com |
| analyst       | analyst@influenceros.example.com    |
| agent         | agent@influenceros.example.com      |

Working without Docker, or running the quality gates, is covered in
[docs/local-development.md](docs/local-development.md).

---

## Repository layout

```
apps/
  api/          FastAPI modular monolith — the whole domain lives here
    app/
      api/      HTTP layer: dependencies, versioned routers, health probes
      core/     settings, errors, security, state machine, acting identity
      modules/  one package per bounded context
      shared/   db, storage, queue, permissions, events, observability
    alembic/    migrations
    tests/
  worker/       ARQ worker entrypoint (imports the api package)
  web/          Next.js App Router frontend
packages/
  ui/           shared React primitives
  types/        TypeScript types generated from the OpenAPI document
  config/       shared eslint / prettier / tsconfig bases
infra/docker/   Dockerfiles and service init scripts
docs/           architecture, domain model, security, ADRs
compose.yml
Makefile
```

---

## Architecture in one page

A **modular monolith**. One deployable codebase, one database, module boundaries
enforced by convention and reviewed in code — not by network calls.
See [docs/architecture.md](docs/architecture.md) and
[ADR-0001](docs/adr/0001-modular-monolith.md).

Four rules shape almost every design decision:

1. **The UI never talks to a generation provider.** Only backend workers execute
   generation jobs. ([ADR-0004](docs/adr/0004-comfyui-adapter.md))
2. **Identity, recipes, workflows and prompts are versioned, not edited.** A change
   appends an immutable revision. ([ADR-0002](docs/adr/0002-versioned-production-assets.md))
3. **Scheduling requires a recorded human approval.** No autonomous publishing.
   ([ADR-0003](docs/adr/0003-human-approval-gate.md))
4. **Every consequential change writes an audit row in the same transaction** as
   the change itself. ([ADR-0007](docs/adr/0007-audit-log-in-transaction.md))

Authorization is per-permission, never per-role, at the endpoint. The `agent` role
is fenced twice — by the matrix and by a runtime guard — so an automated actor can
never publish, approve, change policy or connect a social account.
([ADR-0005](docs/adr/0005-rbac-permission-model.md), [docs/security.md](docs/security.md))

---

## API

REST under `/api/v1`, OpenAPI generated by FastAPI.

```bash
make openapi      # writes docs/api/openapi.json and regenerates packages/types
```

Implemented route groups: `/auth`, `/me`, `/organizations`, `/influencers`,
`/disclosure-policies`, `/audit-logs`, plus unauthenticated `/health/live` and
`/health/ready`.

Route groups from later steps (`/assets`, `/recipes`, `/content`,
`/generation-jobs`, `/qa`, `/approvals`, `/calendar`, `/experiments`,
`/dashboard`) are **deliberately not registered yet** — the generated contract
never advertises an endpoint that does not work.

Errors always use one envelope:

```json
{
  "error": {
    "code": "invalid_transition",
    "message": "Influencer cannot move from 'archived' to 'active': 'archived' is terminal",
    "details": { "current_status": "archived", "requested_status": "active" },
    "request_id": "0b0f4c2e-..."
  }
}
```

---

## Roadmap

Steps are implemented strictly in order; each ends with green gates.

| Step | Scope                                                              | State    |
| ---- | ------------------------------------------------------------------ | -------- |
| 1    | Compose stack, API skeleton, org/membership, migrations, auth stub | **done** |
| 2    | Influencer CRUD, Character Bible versions, RBAC, audit log         | **done** |
| 3    | MinIO presigned uploads, Asset Library, golden references          | next     |
| 4    | Recipes and immutable recipe versions, LoRA/workflow attachment    | planned  |
| 5    | ContentBrief, Kanban, script versions, brief state machine         | planned  |
| 6    | GenerationJob, ARQ worker, `FakeGenerationProvider`, lineage       | planned  |
| 7    | QA reviews, Approval Center, approval gate before calendar         | planned  |
| 8    | Calendar scheduling, operational dashboard widgets                 | planned  |

**Explicit non-goals for the MVP:** automatic publishing to Instagram / TikTok /
YouTube, automated DM or comment replies, autonomous agents that may change policy
or publish, billing, a data warehouse, a marketplace, a mobile app.

---

## Known limitations

Stated plainly, because these are the things a reader would otherwise assume work.

- **Docker Compose is authored but was never started in this environment** — no
  Docker daemon was available. Postgres and Redis were run natively to execute the
  test suite, so the schema, migrations and API are verified; the container images
  and service wiring are not.
- **MinIO / object storage is unverified.** `app/shared/storage/s3.py` provides the
  client and the readiness probe only. Presigned uploads arrive with step 3.
- **The worker has no tasks yet.** `apps/worker` holds the ARQ settings; job
  execution arrives with step 6.
- **No token revocation.** Access and refresh tokens are stateless JWTs with no
  server-side session table, so a leaked token stays valid until it expires. Access
  TTL is 30 minutes by default. See [docs/security.md](docs/security.md).
- **Version immutability is enforced by the application, not by a database
  trigger.** No code path can update a version row and tests assert the repository
  exposes no mutating method, but a direct `UPDATE` in psql would succeed. A
  trigger is proposed in [ADR-0002](docs/adr/0002-versioned-production-assets.md).
- **Playwright E2E is not yet wired.** The end-to-end path is currently verified
  through the API (194 backend tests, plus a scripted live walkthrough). The
  browser-level E2E belongs with step 5, when there is a Kanban flow worth driving.

---

## Documentation

| Document                                               | Contents                                                             |
| ------------------------------------------------------ | -------------------------------------------------------------------- |
| [docs/architecture.md](docs/architecture.md)           | module boundaries, request lifecycle, transactions, deployment shape |
| [docs/domain-model.md](docs/domain-model.md)           | every entity, every status, the transition rules                     |
| [docs/local-development.md](docs/local-development.md) | setup with and without Docker, quality gates, troubleshooting        |
| [docs/security.md](docs/security.md)                   | authn, authz, tenancy, secrets, disclosure obligations, threat notes |
| [docs/adr/](docs/adr/)                                 | architecture decision records 0001–0007                              |
