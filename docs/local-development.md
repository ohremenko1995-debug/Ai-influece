# Local development

Two supported ways to work. Use containers for running the product, native for
iterating on the quality gates.

## Prerequisites

| Tool | Version | Needed for |
|---|---|---|
| Docker + Compose v2 | any current | container path |
| Python | 3.12+ | native path |
| Node | 22+ | frontend |
| pnpm | 10+ | frontend workspace |
| `uv` | 0.8+ | fast Python installs (`pip` also works) |

---

## Container path

```bash
make env      # copy .env.example -> .env (never overwrites an existing .env)
make up       # build images, start postgres, redis, minio, api, worker, web
make migrate-docker
make seed
```

| Service | URL |
|---|---|
| Web | http://localhost:3000 |
| API docs | http://localhost:8000/docs |
| Readiness | http://localhost:8000/health/ready |
| MinIO console | http://localhost:9001 (`influenceros` / `influenceros`) |

Useful targets:

```bash
make ps                  # service status
make logs SERVICE=api    # tail one service
make api-shell           # shell inside the api container
make db-shell            # psql against the dev database
make down                # stop, keep volumes
make down-hard           # stop and DELETE all local data
```

`minio-init` is a one-shot job that creates the asset bucket, enables versioning and
explicitly denies anonymous access — assets are private and always served through
short-lived presigned URLs.

> The compose stack in this repository has **not been executed** in the environment
> where the backend was developed (no Docker daemon was available). The schema,
> migrations, API and tests are verified natively; the images and service wiring are
> not. Expect to iterate on the first `make up`.

---

## Native path

Used to run the quality gates without Docker. You still need PostgreSQL 16 and
Redis reachable on localhost.

```bash
# services (Debian/Ubuntu example)
sudo pg_ctlcluster 16 main start
redis-server --daemonize yes

# databases
sudo -u postgres psql -c "CREATE ROLE influenceros LOGIN PASSWORD 'influenceros' SUPERUSER"
sudo -u postgres createdb -O influenceros influenceros
sudo -u postgres createdb -O influenceros influenceros_test

# project
make env
make install          # apps/api/.venv + pnpm workspace
make migrate
make seed
```

`make env` writes `.env` with `POSTGRES_HOST=postgres` (the compose alias). For the
native path set `POSTGRES_HOST=127.0.0.1`, `REDIS_HOST=127.0.0.1` and
`S3_ENDPOINT_URL=http://127.0.0.1:9000`, or rely on the Makefile targets, which pass
those overrides for you.

Run the API and the web app:

```bash
cd apps/api && ../../apps/api/.venv/bin/uvicorn app.main:app --reload
pnpm --filter @influenceros/web dev
```

---

## Quality gates

```bash
make check          # everything: lint + typecheck + test
make lint           # ruff (check + format --check) and eslint + prettier
make typecheck      # mypy --strict and tsc --noEmit
make test           # pytest and vitest
make format         # ruff format / prettier --write
```

Backend only:

```bash
make lint-api
make typecheck-api
make test-api
```

### What the backend test suite actually does

- Runs against **real PostgreSQL 16**, never SQLite. The schema uses JSONB, partial
  unique indexes, `IDENTITY` and `CHECK` constraints; a different engine would
  validate a different system.
- Builds the schema by running **`alembic downgrade base` then `upgrade head`**, so
  every run proves the migrations apply *and* reverse.
- Isolates each test with a connection-level transaction plus a savepoint-joined
  session (`join_transaction_mode="create_savepoint"`). Application code commits
  normally; the outer transaction is rolled back afterwards.
- Seeds a tenant with **one user per role** so authorization is exercised for all
  seven roles, and a second tenant to prove cross-tenant isolation.

Two pytest settings matter and are easy to break:

```toml
asyncio_default_fixture_loop_scope = "session"
asyncio_default_test_loop_scope    = "session"
```

Fixtures and tests must share one event loop, because the session-scoped engine
holds asyncpg connections and a connection cannot be awaited from a different loop.
Without the second line every database test fails with *"got Future attached to a
different loop"*.

---

## Migrations

```bash
make migration M="add asset tables"   # autogenerate
make migrate                          # upgrade head
make downgrade                        # back one revision
```

Revision ids are sequential by hand (`0001`, `0002`, …) so the order is obvious from
`ls`. Pass `--rev-id` when creating one:

```bash
cd apps/api && ../../apps/api/.venv/bin/alembic revision --autogenerate \
  -m "add asset tables" --rev-id 0002
```

Alembic reads the database URL from application settings, never from `alembic.ini`,
so migrations and the running app cannot disagree about which database they mean.
Override for a one-off run with `ALEMBIC_DATABASE_URL`.

A post-write hook runs `ruff check --fix` and `ruff format` on every generated
migration, so they land already formatted.

**Always read a generated migration before committing it.** Autogenerate is a
starting point: it does not know about data backfills, and it will happily emit a
destructive change.

---

## API contract and frontend types

```bash
make openapi
```

Writes `docs/api/openapi.json` by importing the app (no running server needed) and
regenerates `packages/types` with `openapi-typescript`. Run it after changing any
request or response model, so the frontend types stay in step with the backend.

---

## Seeded data

`make seed` is idempotent — re-running adds only what is missing — and refuses to
run unless `ENVIRONMENT=development`.

It creates the organization `influenceros-studio`, one user per role, and a default
disclosure policy. Password for every seeded user: `influenceros`.

| Role | Email |
|---|---|
| owner | owner@influenceros.example.com |
| creative_lead | creative@influenceros.example.com |
| operator | operator@influenceros.example.com |
| reviewer | reviewer@influenceros.example.com |
| compliance | compliance@influenceros.example.com |
| analyst | analyst@influenceros.example.com |
| agent | agent@influenceros.example.com |

Emails use `example.com` on purpose. `.test`, `.local` and `.invalid` are
special-use TLDs that `email-validator` rejects, so a seeded `@company.local`
address would create a user who can never log in.

### Development login stub

```bash
curl -X POST http://localhost:8000/api/v1/auth/dev-login \
  -H 'Content-Type: application/json' \
  -d '{"email":"owner@influenceros.example.com"}'
```

Passwordless, and guarded twice: the route is only registered when
`ENVIRONMENT=development` **and** `DEV_AUTH_ENABLED=true`, and the service refuses
the call under the same condition. Flipping one variable in staging does not open a
passwordless login.

---

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `ConnectionRefusedError ... 5432` in tests | Postgres is not running, or `POSTGRES_HOST` still says `postgres` on the native path. |
| `Can't locate revision identified by '0001'` | The migration file was deleted while `alembic_version` still records it. `DROP SCHEMA public CASCADE; CREATE SCHEMA public;` on the dev *and* test databases, then regenerate. |
| `got Future attached to a different loop` | `asyncio_default_test_loop_scope` is missing from `[tool.pytest.ini_options]`. |
| `MissingGreenlet: greenlet_spawn has not been called` | A response model touched an unloaded relationship or an expired column. Load the relationship explicitly (assign the object, not just the FK) or ensure the column comes back via RETURNING (`eager_defaults=True`). |
| `FOR UPDATE cannot be applied to the nullable side of an outer join` | A row-lock query inherited an eager `joinedload`. Add `noload(...)` for that relationship. |
| `readiness: object_storage=false` | MinIO is not running or the bucket is missing. `docker compose up minio minio-init`. |
| `InsecureKeyLengthWarning` from PyJWT | `SECRET_KEY` is shorter than 32 bytes (HMAC-SHA256's digest size, RFC 7518 §3.2). |
| Refusing to boot in staging/production | `Settings.validate_production_safety` found a dev placeholder `SECRET_KEY`, a short key, or `DEV_AUTH_ENABLED=true`. |
| A single request logs for minutes | A module-level logger was created with `.bind()` before `configure_logging` ran, freezing structlog's rich exception formatter. Use `get_logger(__name__)` from `app.shared.observability`. |

## Configuration reference

All settings come from the environment; `.env.example` is the annotated list and
contains no real secrets. Notable ones:

| Variable | Effect |
|---|---|
| `ENVIRONMENT` | `development` unlocks the auth stub and relaxes secret checks |
| `SECRET_KEY` | JWT signing key; ≥32 bytes, from the secret manager outside development |
| `DEV_AUTH_ENABLED` | must be false outside development, or the app refuses to boot |
| `API_CORS_ORIGINS` | comma-separated explicit origins; `*` is rejected |
| `LOG_FORMAT` | `console` locally, `json` elsewhere |
| `GENERATION_PROVIDER` | `fake` or `comfyui` (step 6) |
| `POSTGRES_TEST_DB` | the database the test suite rebuilds; never the dev one |
