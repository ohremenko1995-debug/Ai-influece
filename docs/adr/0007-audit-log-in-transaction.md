# ADR-0007 — Write audit entries inside the caller's transaction

- **Status:** accepted
- **Date:** 2026-08-14

## Context

The platform must be able to show every consequential action: who created a character,
who changed a prompt, who approved content, who scheduled it. That trail is the
evidence for compliance questions, so its integrity matters more than its throughput.

Two ways to get it wrong:

1. **A change lands without its audit entry.** The trail then claims something did not
   happen. Any log-shipping or fire-and-forget approach permits this.
2. **An audit entry lands for a change that was rolled back.** The trail then claims
   something happened that did not.

## Decision

`AuditService.record(...)` adds the row to the **same SQLAlchemy session** the domain
service is using, and flushes. It never commits. The request-scoped unit of work commits
both the entity change and the audit row together, or rolls both back.

```python
async with database.session() as session:   # BEGIN
    yield session                           # handler → service → entity + audit row
                                            # COMMIT together / ROLLBACK together
```

**Services never commit.** That single rule is the whole guarantee.

Flushing (not committing) inside `record` is deliberate: a constraint violation
surfaces at the call site, where it can be attributed, rather than at commit time where
it cannot.

### Snapshots, taken at the right moment

`record_entity_change` reads the entity's current column values as `after_data`. The
caller must capture `before` **before** mutating — a snapshot taken afterwards would
record no change at all. Every mutating service follows the same shape:

```python
before = snapshot(entity)
entity.field = new_value
await audit.record_entity_change(actor=..., action=..., entity=entity, before=before)
```

The serialiser converts UUIDs, datetimes, enums and Decimals to JSON-safe values, skips
relationships (an audit row records the entity that changed, not its neighbours), reads
only loaded attributes so it never triggers lazy IO while a transaction is being
finalised, and replaces `password_hash` with `[redacted]` — visible as *changed*, never
as a value.

### A closed action vocabulary

`action` is a `DomainAction` enum member, not a string. Free-text names drift —
`influencer.update` and `influencer_updated` will both appear within a month — and a log
you cannot filter by action is not queryable.

### Ordering comes from a sequence, not a timestamp

`audit_logs.sequence_number` is a `BIGINT IDENTITY`, and it is the column the trail is
ordered by.

This is not a micro-optimisation. PostgreSQL's `now()` returns the **transaction**
timestamp, so every row written by one request carries an identical `created_at`, and
the UUIDv4 primary key gives no tiebreak. A history tab ordered by time showed
"created" and "updated" in arbitrary order — a real bug, caught by a flaky test. An
IDENTITY column is allocated per INSERT and orders rows within a transaction correctly.

`created_at` is kept for date-range filtering, where transaction granularity is exactly
right.

### Append-only in shape, not just by convention

- No `updated_at` on the table — a row that could be edited is not an audit trail.
- `AuditRepository` exposes only `list_entries` and `count_entries`; a test asserts that
  exact set.
- No update or delete endpoint exists.
- Writes go through `AuditService` alone, which is the single place that stamps the
  actor and the request id.

### One documented exception: failed logins

A failed login commits its audit row before raising `401`. The request is about to
fail, and the surrounding unit of work rolls back on exception, which would discard the
evidence of the attempt. Committing there is safe because the transaction contains
nothing else, and it is commented at the call site.

Attempts against *unknown* addresses are logged but not audited: `organization_id` is
non-null and there is no tenant to file them under. A separate security-events stream
is the right home for those, and the gap is recorded in
[security.md](../security.md).

## Consequences

**Gained**

- An audited change either lands with its evidence or does not land at all.
- A refused action writes nothing — verified by a test that asserts an empty trail after
  a `PermissionDeniedError`.
- A no-op update writes nothing, so the trail stays signal.
- Every entry carries `request_id`, tying it to the server logs for the same request.
- `before`/`after` support a computed field-level diff, which is what the history tab
  renders.

**Given up**

- Audit writes are on the request's critical path. Acceptable: one INSERT into an
  append-only table, and correctness here outranks a millisecond.
- The audit table grows with activity and shares the database. Partitioning by
  `created_at` is the obvious future step; the sequence column already gives a stable
  order across partitions.
- Emission is manual — a service that forgets to call `record` produces no entry. The
  mitigation is tests per action rather than a mechanism, because an ORM-event-based
  approach cannot know the actor or the business meaning of a change.

## Alternatives considered

| Alternative | Why not |
|---|---|
| Log to stdout and ship to a log store | Not transactional. A rolled-back change would still be "audited", and a shipping failure loses the trail. Also unqueryable by entity from the product UI. |
| SQLAlchemy `after_flush` event to audit automatically | Cannot know the actor (it is not in the session), cannot express business meaning (`influencer.archived` vs a generic update), and would audit internal bookkeeping writes. Automatic coverage of the wrong data is worse than deliberate coverage of the right data. |
| Database triggers writing audit rows | Same actor problem — the database does not know who is acting — and it moves auditing away from the code that must explain it. Triggers also fire for migrations and manual fixes. |
| A separate audit database | Loses transactional atomicity, which is the entire point, and would need an outbox to approach the same guarantee. |
| Ordering by `created_at` with `clock_timestamp()` | Would fix intra-transaction ordering, but `clock_timestamp()` is non-deterministic within a transaction and makes "these happened atomically" unrepresentable. A sequence separates *when* from *in what order*. |
