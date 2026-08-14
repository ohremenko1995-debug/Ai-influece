# ADR-0003 — A human approval gate in front of every publication surface

- **Status:** accepted
- **Date:** 2026-08-14

## Context

The platform generates photorealistic media and speech for characters that address a
public audience. Two categories of harm follow directly from publishing without a
human decision:

- **Compliance:** undisclosed AI content, or undisclosed advertising.
- **Brand and safety:** a character speaking about a prohibited topic, an
  identity-drifted face, a lip-sync failure that reads as a deepfake artefact.

Automated QA catches the technical class of these (sharpness, duration, sync offset,
identity embedding distance). It cannot judge "is this appropriate for this brand, in
this market, right now".

The platform must also be able to _prove_, after the fact, that a specific person
approved specific text — not merely that an approval step existed.

## Decision

**No content reaches a publication surface without a recorded `ApprovalTask` whose
status is `approved`.** Enforced in the backend domain layer, at three points.

### 1. The state machine forbids the shortcut

`ContentBrief` transitions are a declared table, and the illegal moves are illegal by
absence:

- `generating → approved` does not exist — QA cannot be skipped.
- `draft → published` does not exist.
- `published → anything` does not exist — publication is a fact, not a revisable state.

### 2. Entering `scheduled` requires the approval record

A precondition beyond the transition table, checked in the service, because it depends
on other data:

```
brief.status == approved  AND  exists(ApprovalTask
                                      where content_brief_id = brief.id
                                        and status = approved)
```

The transition table alone is not enough: `approved → scheduled` is a legal move, so
without this check a caller could set the status directly and then schedule.

This mirrors the pattern already implemented for `Influencer` activation, where
`activation_blockers` gates `draft → active` on the adult-representation confirmation,
a disclosure policy and an existing Character Bible.

### 3. Permission separation

`calendar:schedule` is held by `owner` and `creative_lead`. Neither can _decide_ an
approval: `approval:decide` belongs to `owner`, `reviewer` and `compliance`, and
`approval:decide_high_risk` narrows to `owner` and `compliance`.

So the scheduling permission is not a way around the gate — the holder still needs
somebody else's recorded decision. And the `agent` role holds none of these, fenced
twice ([ADR-0005](0005-rbac-permission-model.md)).

### Approval snapshots the text it approved

`ContentPublicationPlan.caption_snapshot` and `disclosure_snapshot` are **copies**
taken at approval time, not references to the current script or policy.

Without this, editing a script or a disclosure policy after approval would silently
change what goes out while the approval record still pointed at it. Copying is what
makes the record mean "this person approved _this text_".

It is also why `DisclosurePolicy` can safely remain mutable-with-audit rather than
versioned: an edit cannot rewrite history, because approved content no longer depends
on the live row.

### Risk level routes the decision

`ContentBrief.risk_level` ∈ `low | medium | high`. A `high` brief requires
`approval:decide_high_risk`. `DisclosurePolicy.requires_high_risk_approval` lets an
organization demand a compliance decision for its own categories.

### No autonomous publishing on the MVP

The furthest an automated path goes is `ready_for_manual_publish`. A human publishes
and records the outcome. Automatic posting to Instagram, TikTok or YouTube is an
explicit non-goal, and the `agent` role cannot reach a publication surface at all.

## Consequences

**Gained**

- A provable chain: QA result → approval decision with a named decider and timestamp →
  scheduled entry → published post, with the exact approved caption and disclosure
  stored alongside.
- Compliance questions are answerable from the database.
- The gate cannot be bypassed by a hand-rolled HTTP call, only by a code change to the
  domain service — which is reviewable.

**Given up**

- Throughput. Every piece of content waits for a person. That is the point.
- Reviewers are a bottleneck; the Approval Center exists to make the queue fast to
  work through, not to remove it.
- Snapshots duplicate text. Trivial storage cost for a meaningful guarantee.

## Alternatives considered

| Alternative                                      | Why not                                                                                                                                                                       |
| ------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Auto-approve `low` risk content                  | The risk level is set by the same person who wrote the brief. Self-assessed risk is not a control.                                                                            |
| Approval as a boolean on `ContentBrief`          | Loses who decided, when, with what notes, and cannot express `revision_requested` or `escalated`. A boolean cannot be audited meaningfully.                                   |
| Frontend-only gating (hide the button)           | Any HTTP client bypasses it. The requirement is explicit that button visibility is not the enforcement point.                                                                 |
| Approve at publish time instead of schedule time | Scheduling is the last human touchpoint before content is queued to go out; a gate after that leaves a window where unapproved content sits in the calendar looking approved. |
