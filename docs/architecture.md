# Architecture

## Shape

A **modular monolith**: one Python codebase, one PostgreSQL database, two process
types (HTTP API and background worker), one frontend.

```
                    browser
                       │
                 Next.js (web)
                       │  fetch /api/v1/*
                       ▼
   ┌──────────────────────────────────────────────┐
   │  FastAPI (api)                               │
   │  ┌────────────────────────────────────────┐  │
   │  │ app/api      routers, deps, health     │  │
   │  ├────────────────────────────────────────┤  │
   │  │ app/modules  bounded contexts          │  │
   │  ├────────────────────────────────────────┤  │
   │  │ app/shared   db, storage, queue, rbac  │  │
   │  └────────────────────────────────────────┘  │
   └───────┬──────────────┬───────────────┬───────┘
           │              │               │
      PostgreSQL       Redis           S3/MinIO
           ▲              │               ▲
           │              │ ARQ queue     │
   ┌───────┴──────────────▼───────────────┴───────┐
   │  ARQ worker — the ONLY process that calls a  │
   │  generation provider (ComfyUI, external API) │
   └──────────────────────┬───────────────────────┘
                          ▼
                    ComfyUI / ffmpeg
```

The browser never reaches a generation provider, and neither does the API process.
That is a hard rule, not a convention: providers are resolved inside the worker.

## Module anatomy

Every bounded context is a package under `app/modules/` with the same five files:

| File            | Responsibility                                                   |
| --------------- | ---------------------------------------------------------------- |
| `models.py`     | SQLAlchemy tables. No business logic.                            |
| `schemas.py`    | Pydantic request/response models. Validation of _shape_.         |
| `repository.py` | Queries. Always filtered by `organization_id`. No authorization. |
| `service.py`    | Domain rules, authorization, audit emission. Never commits.      |
| `router.py`     | HTTP mapping only. No rules.                                     |

Additional files appear where a context needs them — `state_machine.py` for a
status table, `serialization.py` for the audit snapshot logic.

### Dependency direction

```
router  →  service  →  repository  →  models
   ↓         ↓
 schemas   shared/*  (db, permissions, events, observability, storage, queue)
```

`shared/*` never imports from `modules/*`. A module may call another module's
_service or repository_, never reach into its tables. Cross-module reads currently
in use: `character_versions` reads through `InfluencerRepository` to check tenancy
before touching a version row, and `influencers` reads
`InfluencerVersionRepository` to compute activation blockers.

### Why the model registry exists

`app/shared/db/registry.py` imports every model module. SQLAlchemy resolves
`relationship("InfluencerVersion")` by name at first use, so a process that
imported only _some_ model modules fails at runtime rather than at import.
`build_database()` imports the registry itself, which means no entrypoint — API,
worker, CLI, tests — can forget. This was a real bug before it was structural: the
seed CLI crashed with `NameError: name 'InfluencerVersion' is not defined`.

## Request lifecycle

```
1  RequestContextMiddleware      assigns/echoes X-Request-ID, stores it on
                                 request.state and in a context var, logs one line
2  CORSMiddleware                explicit origins only, never "*"
3  get_current_actor             decodes the JWT, resolves the organization from
                                 X-Organization-Id → token claim → sole membership,
                                 loads the live Membership, builds CurrentActor
4  RequirePermission(...)        route-declared permission check
5  get_session                   opens ONE unit of work for the request
6  handler → service             service re-checks the permission, applies rules,
                                 writes the entity change AND the audit row
7  commit                        on clean return; rollback on any exception
8  response model                Pydantic serialises the ORM object
```

Step 4 and step 6 both check the same permission on purpose. The route dependency
makes the requirement visible in the OpenAPI document and fails fast; the service
check is what protects a non-HTTP caller such as the worker or the seed CLI.

### The organization header is a selector, not a grant

`X-Organization-Id` chooses which of the caller's memberships to act under. An
active `Membership` must exist regardless, so sending another tenant's id yields
`403 not_a_member`. Reading another tenant's _entity_ yields `404`, not `403`, so
the API never confirms that a row exists in someone else's organization.

## Transactions

One unit of work per request, owned by the `get_session` dependency.

```python
async with database.session() as session:   # BEGIN
    yield session                           # handler + services
                                            # COMMIT on clean exit
                                            # ROLLBACK on exception
```

**Services never commit.** That single rule is what makes the audit guarantee real:
an entity change and its audit row are in the same transaction, so either both land
or neither does. A service that committed early would let a change survive while
its audit entry was rolled back.

One deliberate exception: a failed login commits its audit row before raising
`401`, because the request is about to fail and the surrounding unit of work would
otherwise discard the evidence. It is commented at the call site.

## Ordering inside a transaction

PostgreSQL's `now()` returns the **transaction** timestamp, so every audit row
written by one request shares a `created_at`, and the UUIDv4 primary key is no
tiebreak. `audit_logs.sequence_number` is a `BIGINT IDENTITY` allocated per INSERT
and is the column the trail is ordered by. Without it, an entity history tab would
show "created" and "updated" in arbitrary order.

## Concurrency

Appending a Character Bible version takes a row lock on the influencer
(`SELECT ... FOR UPDATE`) before computing `max(version_number) + 1`, which
serialises concurrent writers. The database backs this up:

- `uq_influencer_versions_influencer_id_version_number` — no duplicate numbers.
- `uq_influencer_versions_influencer_id_current` — a **partial unique index**
  `WHERE is_current`, so at most one current version per influencer.

The lock query must not eagerly join `disclosure_policy`: PostgreSQL refuses
`FOR UPDATE` on the nullable side of an outer join, so the relationship is loaded
with `noload()` there.

## Schema conventions

| Decision                                    | Reason                                                                                                                                                        |
| ------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| UUIDv4 primary keys                         | no cross-tenant id guessing; ordering always via `created_at`/sequence, never the key                                                                         |
| `TIMESTAMPTZ`, server defaults              | one clock authority (the database), never the app server's                                                                                                    |
| Enums as `VARCHAR` + `CHECK`                | adding a value is a plain `ALTER TABLE`; native `ALTER TYPE ... ADD VALUE` is irreversible                                                                    |
| `JSONB`, not `JSON`                         | contents stay queryable and indexable (`findings`, `visual_constraints`)                                                                                      |
| Explicit constraint naming convention       | without it Alembic cannot drop unnamed constraints, and every later change becomes hand-written SQL                                                           |
| `eager_defaults=True` on timestamped tables | `onupdate=func.now()` is a SQL expression; without RETURNING, `updated_at` expires and a response model triggers a synchronous reload inside an async request |
| No hard deletes                             | `archived_at` + terminal `archived` status; membership revocation is `revoked_at`                                                                             |

## Error handling

Four handlers in `app/main.py` produce one envelope for the entire API.

| Raised                                                              | Status | Notes                                                                        |
| ------------------------------------------------------------------- | ------ | ---------------------------------------------------------------------------- |
| `AuthenticationError`                                               | 401    | codes: `token_missing`, `token_invalid`, `token_expired`, `token_wrong_type` |
| `PermissionDeniedError`                                             | 403    | carries `required_permission`                                                |
| `NotFoundError`                                                     | 404    | also used for cross-tenant reads                                             |
| `ConflictError` / `InvalidTransitionError` / `ImmutableEntityError` | 409    | transition errors carry current/requested status                             |
| `PolicyViolationError` / `DomainValidationError`                    | 422    | e.g. `activation_blocked` with the blocker list                              |
| `RequestValidationError`                                            | 422    | only `location`, `message`, `type` are copied out                            |
| anything else                                                       | 500    | traceback to the log, nothing internal to the client                         |

Two details that are easy to get wrong and were fixed here:

- Pydantic's raw validation errors carry `ctx` (a live `ValueError` object),
  `input` (the rejected value, possibly a credential) and `url`. None of them reach
  the response.
- A 500 response keeps its `request_id`. The context var is reset by the middleware
  before Starlette's server-error handler runs, so the id is read from
  `request.state` first.

## Logging

structlog, console renderer locally and JSON everywhere else. A processor injects
the request id and the acting identity, so no call site has to pass them.

Two non-obvious constraints, both discovered by measurement:

- Module-level loggers must stay **lazy**. `structlog.get_logger(...)` returns a
  proxy that materialises on first use, i.e. after `configure_logging` has run.
  Calling `.bind()` at import time freezes structlog's _default_ processor chain,
  whose exception formatter is rich's — and rich pretty-prints every frame's
  locals. One unhandled request exception rendered that way took **253 seconds** of
  CPU and 472 million function calls.
- The console renderer is configured with `exception_formatter=plain_traceback`
  for the same reason.

## Deployment shape

| Service    | Command                          | Notes                                                |
| ---------- | -------------------------------- | ---------------------------------------------------- |
| `api`      | `uvicorn app.main:app`           | stateless, horizontally scalable                     |
| `worker`   | `arq worker.main.WorkerSettings` | same image, same domain code, different process type |
| `postgres` | —                                | single primary                                       |
| `redis`    | —                                | queue + cache                                        |
| `minio`    | —                                | S3-compatible in production                          |

`apps/worker` contains the ARQ settings module and nothing else of substance. The
worker needs the same models, services and repositories as the API; duplicating them,
or putting them behind an internal HTTP call, would create two sources of truth for
the domain.

Its one registered job is a per-minute database heartbeat. ARQ refuses to construct a
worker with no functions and no cron jobs, so _something_ has to be registered; a
no-op task that reports success would violate the rule against placeholders, and the
heartbeat is the smallest thing that is genuinely worth having — the worker container
has no HTTP surface, so without it a worker that has lost its database connection
looks exactly like an idle one. Generation tasks arrive with step 6.

## What is intentionally absent

Empty module packages exist for `assets`, `recipes`, `workflows`, `content`,
`generation_jobs`, `qa`, `approvals`, `calendar` and `dashboard`. They declare the
agreed boundary and nothing else. No stub routers, no placeholder models — the
OpenAPI document must never advertise an endpoint that does not work.
