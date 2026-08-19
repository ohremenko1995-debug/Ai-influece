# ADR-0005 — Automatic publishing, only of an approved snapshot

- **Status:** accepted
- **Date:** 2026-08-19
- **Supersedes:** the donor's [ADR-0003](../../../docs/adr/0003-human-approval-gate.md),
  which forbade automatic publishing entirely

## Context

The donor's rule was absolute: no autonomous publishing, scheduling requires a recorded
human approval and a person performs the publish. That was correct for the donor, because
its approval covered "this content item" and the content item could still change afterwards.
An approval that does not pin down what was approved cannot safely authorise a machine to
act later.

This product must publish on a schedule, unattended, including after the machine has been
off. So the rule has to change — without giving up the property that made it worth having:
a person decides what the audience sees.

The requirement, as stated:

> Automatic publishing is allowed only for a specific platform version that holds a valid
> human approval. Any change to the file, text, disclosure, account, time or platform
> settings voids that approval.

## Decision

**A person approves one exact artefact. The scheduler may execute that decision and nothing
else.**

### Approval is per platform target, never per publication

One publication fans out into a `PublicationTarget` per account. The Instagram version and
the Telegram version have different text, different settings and different rules. A single
button may approve several targets at once, but it writes a separate `ApprovalDecision` for
each. There is no group-level approval that a target can inherit.

### The snapshot hash

Before an approval is recorded, a hash is computed over everything that determines what the
audience will see:

- the media asset ids **and their SHA-256** ([ADR-0004](0004-managed-local-media-library.md))
- caption, title, description
- the disclosure text
- the account and destination
- the content type
- the resolved platform settings
- the scheduled time, where workspace policy treats a time change as significant

The hash is stored with the decision. **Immediately before publishing, it is recomputed.**

```text
match     → publish
mismatch  → the target returns to draft or ready_for_approval, and does not publish
```

A mismatch is never a warning to click past. If the artefact changed, the decision was
about something else.

### Idempotency

Every publish attempt carries an idempotency key derived from the target and the attempt.
A lost response, a retried job or a duplicated lease cannot produce a second post: the
connector either recognises the key or the status is polled before anything new is created.

### Late publication

If the computer was off when a slot passed, at the next start-up:

1. find `scheduled` jobs whose time has passed
2. **re-validate the approval and the hash** — an expired or voided approval stops here
3. move to `late_pending`
4. execute
5. record `scheduled_at`, `published_at` and `late_by_seconds`
6. tell the user it went out late

Late publication is automatic because the decision was already made and is still valid.
Silently dropping it would be worse: a person planned that post and would have no signal it
never happened.

### Retries, bounded

| Failure                          | Behaviour                                    |
| -------------------------------- | -------------------------------------------- |
| network, 5xx, rate limit         | exponential backoff with jitter              |
| invalid media, invalid settings  | no automatic retry — a person must fix it    |
| expired token                    | one refresh attempt, then a reconnect action |
| duplicate / idempotency conflict | check status; never create a second post     |

Maximum automatic attempts is configurable, default 5. A token that needs the user's
attention produces a reconnect prompt, not an infinite retry loop.

### What automation may never do

The `agent` role — and therefore anything automated — cannot approve, cannot acknowledge a
warning, cannot change platform settings after approval, cannot schedule, cannot publish,
and cannot enable the media relay. The scheduler runs as the system actor and executes
approved decisions; it does not make them.

## Consequences

**Gained**

- Scheduled publishing works, unattended, which is a core product requirement.
- The audit trail can prove what was approved, by whom, and that what went out was byte-for-byte
  that thing.
- Editing after approval is safe by construction: the edit voids the approval instead of
  quietly changing a scheduled post.
- A missed slot is recovered and visibly labelled rather than lost.

**Given up**

- **Friction.** A one-word caption fix on an approved target means approving again. That is the
  cost of the guarantee, and reducing it by loosening the hash would remove the guarantee.
- **The hash's inputs are a design commitment.** Anything not hashed can change after approval
  without voiding it. Adding a field that affects the audience means adding it to the hash,
  and forgetting is a silent hole — so the hash inputs need a test that enumerates them.
- **A grey area on time.** Whether moving a post by ten minutes voids approval is policy, not
  logic. It is a workspace setting, with a documented default.
- **The scheduler holds real authority.** A bug there publishes. Hence the lease, the
  idempotency key, the pre-publish re-check, and the fake-connector end-to-end test as a
  release gate.

## Alternatives considered

| Alternative                                    | Why not                                                                                                                                  |
| ---------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| Keep the donor's rule: a person clicks publish | Makes scheduling impossible, which is the product. A person cannot be present at 07:00 for five platforms.                               |
| Approve the publication, not each target       | The platform versions differ. Approving the Instagram text does not mean approving the TikTok text.                                      |
| Warn on snapshot mismatch and publish anyway   | Turns the guarantee into a suggestion. The whole point is that the machine cannot publish something a person did not see.                |
| Hash only the media                            | The caption and the disclosure are what regulators and audiences read. Excluding them would be the most consequential omission possible. |
| Drop a missed slot instead of publishing late  | The user planned that post and gets no signal. Late-and-labelled beats silently-never.                                                   |
| Let the agent role approve its own drafts      | An automated actor approving its own work is not an approval. The fence exists precisely to make this impossible.                        |
