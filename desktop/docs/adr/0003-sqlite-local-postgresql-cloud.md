# ADR-0003 — SQLite locally, PostgreSQL kept possible for the cloud

- **Status:** accepted
- **Date:** 2026-08-19

## Context

The donor stores everything in PostgreSQL and uses it well: partial unique indexes, a
`BIGINT IDENTITY` sequence for audit ordering, `CHECK` constraints for every enum, native
UUIDs.

[ADR-0001](0001-desktop-local-first.md) rules out requiring PostgreSQL on a user's PC. But
the product roadmap ends at a commercial multi-tenant service, which will need it. So the
question is not "which database" but "how to use one now without foreclosing the other".

## Decision

**SQLite is the local store. The domain is written so PostgreSQL remains a configuration
change rather than a rewrite.**

### Local configuration

| Setting        | Value    | Why                                                                        |
| -------------- | -------- | -------------------------------------------------------------------------- |
| `journal_mode` | `WAL`    | a reader (the UI) and the writer (the scheduler) must not block each other |
| `foreign_keys` | `ON`     | off is SQLite's default; every FK in the schema would be decorative        |
| `busy_timeout` | set      | a brief lock contention should wait, not raise                             |
| `synchronous`  | `NORMAL` | with WAL, durable enough for a desktop app, and much faster                |

One file, at `<DATA_ROOT>/database/influenceros.db`, backed up before every migration.

### Portability rules

1. **No raw SQL in services.** Queries go through SQLAlchemy Core or the ORM.
2. **No SQLite-only types.** UUIDs and timestamps go through the donor's type decorators, so
   the storage representation is one place to change.
3. **UTC everywhere in the database.** SQLite has no timezone-aware type, so a naive local
   timestamp would be a silent data-loss bug the moment a user travels or the clock shifts.
4. **No reliance on SQLite's type coercion.** SQLite will accept a string in an integer
   column; PostgreSQL will not. Validation happens in Pydantic and the ORM, above the
   database.
5. **Alembic uses batch operations** for `ALTER`, because SQLite cannot drop or alter a
   column in place. Batch mode's table-rebuild works on both.
6. **Constraints are declared even where SQLite enforces them weakly.** They are documentation
   and they become real on PostgreSQL.

### Deliberate divergences from the donor

| Donor mechanism                         | Local equivalent                                                                                                  |
| --------------------------------------- | ----------------------------------------------------------------------------------------------------------------- |
| `BIGINT IDENTITY` for audit ordering    | `INTEGER PRIMARY KEY AUTOINCREMENT` on an audit sequence column — monotonic, and unlike `created_at` it is unique |
| Partial unique index `WHERE is_current` | supported by SQLite since 3.8; kept as-is                                                                         |
| Native `uuid` column type               | 16-byte `BLOB` or a canonical string via the type decorator; never a locale-dependent format                      |
| Server-side `now()`                     | timestamps generated in Python, in UTC — SQLite's `CURRENT_TIMESTAMP` is not timezone-aware                       |

### Migrations

Every schema change ships an Alembic revision with a working `downgrade`, plus a test that
upgrades to head, downgrades to base and upgrades again. This matters more here than in the
donor: a failed migration on a server is an incident with a DBA and a backup, while on a
desktop it is one person's only copy of their work. Hence the backup-before-migrate rule
and the refusal to continue on a partially migrated schema
([ADR-0009](0009-signed-update-channel.md)).

## Consequences

**Gained**

- Zero-install persistence, with real transactions and real foreign keys.
- Tests run against a file, so the suite needs no service.
- A backup is a file copy, which makes the pre-migration safety net trivial to implement
  correctly.
- The cloud version stays a deployment decision instead of a rewrite.

**Given up**

- **One writer.** Concurrency is bounded by SQLite, so scheduler and UI writes serialise. At
  desktop scale this is invisible; it is a hard ceiling for the team version.
- **Weaker constraint enforcement.** SQLite's type affinity means a bug that PostgreSQL would
  reject may be stored. Mitigated by validation above the database, not by the database.
- **Migration friction.** Batch operations are more verbose and rebuild tables, so a large
  media library makes a schema change measurably slow.
- **Portability discipline is manual.** Nothing stops someone writing PostgreSQL-only SQL in a
  service; only review and this document do. A CI job running the suite against PostgreSQL
  arrives with the cloud stage.
- **No `LISTEN`/`NOTIFY`.** The scheduler polls, with a lease. Fine for a per-minute loop.

## Alternatives considered

| Alternative                            | Why not                                                                                                                        |
| -------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------ |
| Bundle PostgreSQL                      | ~300 MB, a service to supervise, a data directory to migrate across versions, and a port to defend — to serve a single writer. |
| DuckDB                                 | Excellent for analytics, wrong for a transactional workload with many small writes.                                            |
| JSON or TOML files                     | No transactions. The core rule of this product is that a change and its audit row land together; files cannot express that.    |
| An ORM-neutral abstraction of our own  | A second abstraction on top of SQLAlchemy, which is already the abstraction. More code, less capability.                       |
| Accept SQLite forever, drop PostgreSQL | Forecloses the stated commercial direction to save a handful of type decorators and a lint rule.                               |
