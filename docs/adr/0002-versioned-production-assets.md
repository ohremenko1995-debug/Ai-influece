# ADR-0002 — Version production identity and recipes; never edit them

- **Status:** accepted
- **Date:** 2026-08-14

## Context

The platform's core promise is that any generated output can be explained. Given an
image produced three months ago, an operator must be able to answer: which character
identity constrained it, which prompt template, which model and LoRA, which workflow
version, which parameters.

If a Character Bible or a recipe were edited in place, that question becomes
unanswerable the moment someone changes a field. The output would still exist, but the
inputs that produced it would be gone — and no audit diff can reconstruct a prompt
template from a chain of edits.

## Decision

Identity, recipes, workflows, prompts and scripts are **append-only versions**. A
change produces revision N+1; nothing is updated in place.

Applies to: `InfluencerVersion` (built), `VoiceProfile`,
`GenerationRecipeVersion`, `ContentScriptVersion`, `AssetVersion`.

### Each version is a complete snapshot

Not a patch. A reader of version 7 sees the full identity as it stood, without
replaying six diffs. Storage is negligible — these are text and small JSON documents,
not media — and the alternative makes historical reads both slow and fragile.

### One current version, marked in the row

`is_current` on the version table, rather than a `current_version_id` pointer on the
parent. The parent stays free of a circular foreign key, and "which version was
current" is answerable from the version table alone.

Enforced by a **partial unique index**:

```sql
CREATE UNIQUE INDEX uq_influencer_versions_influencer_id_current
    ON influencer_versions (influencer_id) WHERE is_current;
```

The application must therefore demote the previous current row _before_ inserting the
new one. That ordering is a constraint the database imposes, not a convention the code
hopes to follow.

### Gapless numbering under concurrency

`version_number` starts at 1 and has no gaps. Two concurrent writers must not pick the
same number, so creation:

1. takes a row lock on the parent (`SELECT ... FOR UPDATE`),
2. computes `max(version_number) + 1`,
3. demotes the current row,
4. inserts.

Backed by `unique (influencer_id, version_number)` and `CHECK (version_number >= 1)`.

A practical wrinkle: PostgreSQL refuses `FOR UPDATE` on the nullable side of an outer
join, so the lock query must not inherit an eager `joinedload` (the influencer's
`disclosure_policy` is loaded with `noload()` there).

### Immutability is enforced by absence of a path

There is no update endpoint and no mutating method on the version repository. A test
asserts the exact set of public repository methods, so adding `update_version` fails
the build.

`is_current` is the sole exception, and it is only touched by a narrowly scoped
`demote_current` that writes nothing else.

### Authorship

`created_by` is a non-null foreign key to `users`. A system actor is refused with
`user_actor_required`: identity revisions are not automatable, and "who decided this
character may say X" must always name a person.

### Ordering, not identity, comes from timestamps

Primary keys are UUIDv4, which carry no order. Chronology comes from
`version_number`, `created_at`, or — in the audit log — a `BIGINT IDENTITY` sequence.
Nothing in the system infers order from a key.

## Consequences

**Gained**

- Any historical generation is explainable from stored rows.
- A prompt or identity change cannot retroactively alter what an earlier output was
  produced from.
- Version history is a natural UI: a list, with a diff between any two revisions.
- Rollback is "make version 3 current again", not a restore from backup.

**Given up**

- More rows, and every write is two statements (demote + insert) inside a lock.
- Callers must send complete payloads, not partial patches. Deliberate: a partial
  patch on a snapshot is ambiguous.
- The application layer, not the database, refuses updates.

## Known gap

A direct `UPDATE influencer_versions SET biography = ...` in psql would succeed. The
guarantee is "no code path can do this", not "the database forbids it".

Proposed hardening, deferred until there is a second versioned entity to justify the
shared machinery:

```sql
CREATE FUNCTION reject_version_mutation() RETURNS trigger AS $$
BEGIN
    IF NEW.is_current IS DISTINCT FROM OLD.is_current
       AND to_jsonb(NEW) - 'is_current' = to_jsonb(OLD) - 'is_current' THEN
        RETURN NEW;   -- only the current marker moved
    END IF;
    RAISE EXCEPTION 'influencer_versions rows are immutable';
END;
$$ LANGUAGE plpgsql;
```

## Alternatives considered

| Alternative                           | Why not                                                                                                                                                                                        |
| ------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Mutable rows + audit diffs            | An audit diff records _that_ a prompt changed, not the template as it stood. Reconstructing a historical prompt from a diff chain is error-prone, and one missing entry breaks it permanently. |
| Event sourcing                        | Full replay for every read is disproportionate. Versioned snapshots give the same auditability for the entities that need it, at a fraction of the complexity.                                 |
| Temporal tables / `SYSTEM VERSIONING` | Not native to PostgreSQL; extensions or triggers would be needed, and the version number would stop being a first-class domain concept the UI can show.                                        |
| `current_version_id` on the parent    | Circular FK, and two rows to keep consistent instead of one partial index.                                                                                                                     |
