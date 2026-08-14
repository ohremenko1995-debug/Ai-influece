# ADR-0001 — Modular monolith first

- **Status:** accepted
- **Date:** 2026-08-14
- **Deciders:** AI/Generative AI lead (single primary user), engineering

## Context

InfluencerOS spans eleven bounded contexts (auth, influencers, character versions,
assets, recipes, workflows, content, generation jobs, QA, approvals, calendar,
audit, dashboard) that are heavily interconnected: a generation job references a
recipe version, which references a LoRA asset version, which belongs to an
influencer, whose Character Bible constrains the prompt. Almost every read crosses
two or three of those contexts.

The team is one technically strong lead. Traffic is internal, in the order of tens of
requests per minute. The hard requirements are reproducibility, traceability and a
complete audit trail — not independent scaling.

## Decision

Build a **modular monolith**: one Python codebase, one PostgreSQL database, two
process types (HTTP API and background worker), one frontend.

Module boundaries are expressed in the package layout and enforced by review, not by
the network:

```
app/modules/<context>/  models.py  schemas.py  repository.py  service.py  router.py
app/shared/             db  storage  queue  permissions  events  observability
```

Rules:

1. `shared/*` never imports from `modules/*`.
2. A module may call another module's **service or repository**, never reach into its
   tables.
3. `router` contains no business rules; `service` owns rules, authorization and audit
   emission; `repository` owns queries and never authorizes; `models` hold no logic.
4. Services never commit — the request-scoped unit of work does.

### Worker packaging

`apps/worker` contains only the ARQ `WorkerSettings` module and its Dockerfile. The
domain code lives in `apps/api/app` and the worker image installs that package.

The worker needs the same models, services and repositories as the API. Duplicating
them, or putting them behind an internal HTTP call, would create two sources of truth
for the domain. Two process types over one codebase is the smaller cost.

### Enumerations

Status columns are stored as `VARCHAR` with a `CHECK` constraint
(`Enum(..., native_enum=False)`), not as PostgreSQL native enums.

Native enums require `ALTER TYPE ... ADD VALUE` to extend, which historically could
not run inside a transaction and **cannot be reversed at all**. This schema has many
status columns and several will gain values (the `ContentBrief` machine alone has
eleven states). A checked `VARCHAR` is a plain `ALTER TABLE` in both directions.

Cost: a check constraint is slightly weaker documentation than a named type, and
migrations must remember to update the constraint. Both are acceptable.

## Consequences

**Gained**

- One transaction spans a change and its audit row, which is what makes
  [ADR-0007](0007-audit-log-in-transaction.md) possible at all. Distributed services
  would need a saga or an outbox for the same guarantee.
- Foreign keys enforce lineage. `generation_job_id` on an asset version is a real FK,
  not an eventually-consistent identifier.
- One deployment, one migration history, one place to look when something is wrong.
- Refactoring across contexts is a normal code change.

**Given up**

- No independent scaling per context. Acceptable: the expensive work is generation,
  which already runs in a separate worker process that scales on its own.
- Boundaries can be violated by a careless import. Mitigated by review, by the
  five-file module shape making violations obvious, and by `shared/*` having no
  dependency on `modules/*`.
- A single database is a single failure domain.

**Migration path if it is ever needed:** the module boundary is already the seam. A
context would be extracted by replacing direct service calls with a client, and its
tables with a separate schema. The audit guarantee would then need an outbox. Nothing
in the current design blocks that, and nothing anticipates it either.

## Alternatives considered

| Alternative                                       | Why not                                                                                                                                                                              |
| ------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Microservices per context                         | Eleven services for one engineer. Cross-context reads become network calls, and the audit atomicity guarantee needs a distributed transaction pattern before any feature ships.      |
| Single-file "just get it working" app             | The audit and versioning rules must be enforced in one place per entity. Without module boundaries those rules end up duplicated in route handlers, which is exactly how they drift. |
| Modular monolith with separate schemas per module | Adds migration and permission complexity now to buy an extraction that may never happen. Cross-schema foreign keys work but complicate Alembic autogenerate.                         |
