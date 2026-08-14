# Domain model

Legend: **[built]** exists in migration `0001`; **[step N]** specified, arriving in
that MVP step.

```
Organization 1─* Membership *─1 User
Organization 1─* DisclosurePolicy
Organization 1─* Influencer  ─1 DisclosurePolicy
Influencer   1─* InfluencerVersion        (append-only, one is_current)
Influencer   1─* VoiceProfile            [step 3]
Organization 1─* Asset  1─* AssetVersion [step 3]
Organization 1─* GenerationRecipe 1─* GenerationRecipeVersion [step 4]
Organization 1─* ContentBrief 1─* ContentScriptVersion        [step 5]
ContentBrief 1─* GenerationJob ─1 GenerationRecipeVersion     [step 6]
ContentBrief 1─* QAReview ─1 AssetVersion                     [step 7]
ContentBrief 1─* ApprovalTask                                 [step 7]
ContentBrief 1─* ContentPublicationPlan                       [step 8]
Organization 1─* Experiment                                   [step 8]
Organization 1─* AuditLog
```

---

## Tenancy and identity

### Organization **[built]**

`id`, `name`, `slug` (globally unique), `created_at`, `updated_at`.

The tenant. Every production record carries `organization_id`, and every repository
query filters on it. A lookup by primary key alone does not exist anywhere in the
codebase.

### User **[built]**

`id`, `email` (unique, casefolded), `display_name`, `status`, `created_at`,
`updated_at`, plus `password_hash`.

`password_hash` is not in the specified domain model because it is a credential
detail, not a domain attribute. It is nullable — an invited user has no credential
yet, an SSO-backed account never will — and it is never serialised into a response
or an audit row (the audit snapshot replaces it with `[redacted]`).

| `status` | Meaning |
|---|---|
| `invited` | created, cannot authenticate |
| `active` | the only status that can authenticate |
| `suspended` | temporarily blocked |
| `disabled` | permanently blocked |

### Membership **[built]**

`id`, `organization_id`, `user_id`, `role`, `created_at`, `revoked_at`.

Binds a user to an organization with exactly **one** role, so the same person can be
an operator in one organization and a reviewer in another. Authorization is always
resolved per `(user, organization)`.

Unique on `(organization_id, user_id)`. Revocation is a soft delete: the row is what
explains who had access when a historical action was taken, so it is never removed.

### Roles

| Role | Purpose |
|---|---|
| `owner` | full authority, including membership and social connections |
| `creative_lead` | identity, recipes, assets, content, scheduling — but **not** approval decisions |
| `operator` | produces content and runs jobs; no identity, no policy, no scheduling |
| `reviewer` | QA and approval decisions up to medium risk |
| `compliance` | policy authorship and high-risk approval decisions |
| `analyst` | read-only plus the audit trail |
| `agent` | automation identity: reads context, drafts content, queues jobs — nothing else |

The permission matrix, the separation-of-duties reasoning and the agent fence are in
[ADR-0005](adr/0005-rbac-permission-model.md) and [security.md](security.md).

---

## Disclosure and compliance

### DisclosurePolicy **[built]**

Not present in the original specification, but `Influencer.disclosure_policy_id`
requires it, so the entity is defined here.

`id`, `organization_id`, `code`, `name`, `ai_disclosure_required`,
`ai_disclosure_text`, `advertising_disclosure_required`,
`advertising_disclosure_text`, `requires_high_risk_approval`, `is_default`,
`notes`, `created_at`, `updated_at`. Unique on `(organization_id, code)`.

It encodes the two disclosures the platform must be able to prove it required: that
the character is AI-generated, and that a given piece of content is advertising.

**Mutable, not versioned** — the platform rule allows "an immutable version *or* an
audit-log entry", and every field change emits `disclosure_policy.updated` with
before/after data. Content that has been approved snapshots the disclosure text it
was approved with, so editing a policy cannot retroactively change what a reviewer
signed off.

---

## Influencer registry

### Influencer **[built]**

`id`, `organization_id`, `code`, `public_name`, `status`, `niche`,
`primary_language`, `primary_market`, `adult_representation_confirmed`,
`disclosure_policy_id`, `created_at`, `updated_at`, `archived_at`.

Unique on `(organization_id, code)` — codes are per-tenant, not global. `code` is
immutable after creation: it is the stable identifier that will appear in storage
keys and audit rows, so `PATCH` does not accept it.

`status` is not accepted by `PATCH` either. It moves only through
`POST /influencers/{id}/status`, so the state machine always runs.

#### Lifecycle

```
draft ──► active ◄──► paused
  │         │           │
  └─────────┴───────────┴──► archived   (terminal)
```

| From | To |
|---|---|
| `draft` | `active`, `archived` |
| `active` | `paused`, `archived` |
| `paused` | `active`, `archived` |
| `archived` | — |

`archived` is terminal on purpose. Reviving a retired character would silently reuse
an identity whose audit history says it was retired; a new character gets a new code.
An archived influencer is also read-only: updates and new Character Bible versions
are refused with `409 influencer_archived`.

#### Activation preconditions

`draft → active` (and `paused → active`) additionally requires **all** of:

1. `adult_representation_confirmed` is true — an explicit record that the character
   depicts an adult. Never defaulted to true.
2. `disclosure_policy_id` is set — a character cannot go live without a policy
   stating how its AI nature is disclosed.
3. At least one `InfluencerVersion` exists — no character goes live without a
   Character Bible.

Unmet preconditions produce `422 activation_blocked` with the full list in
`details.blockers`. The same list is exposed on the detail response as
`activation_blockers`, so the UI can explain a disabled button instead of hiding it.

Withdrawing `adult_representation_confirmed` from an `active` influencer is refused
(`422 confirmation_required_while_active`) — pause it first. Otherwise a live
character would exist without the compliance record that allowed its launch.

### InfluencerVersion — the Character Bible **[built]**

`id`, `influencer_id`, `version_number`, `change_summary`, `biography`,
`tone_of_voice`, `personality_traits` (jsonb), `prohibited_topics` (jsonb),
`visual_constraints` (jsonb), `speech_constraints` (jsonb), `created_by`,
`created_at`, `is_current`.

**Append-only.** There is no update path anywhere: no endpoint, and no mutating
method on the repository (a test asserts the exact set of public methods). A change
to a character's identity produces version N+1 and moves `is_current`.

Each version is a **complete snapshot**, not a patch, so a later reader never has to
replay a chain of diffs to know what the constraints were when a generation ran.

Guarantees, enforced by the database and not only by the service:

| Guarantee | Mechanism |
|---|---|
| gapless numbering from 1 | row lock on the influencer + `unique (influencer_id, version_number)` |
| `version_number >= 1` | `CHECK` constraint |
| at most one current version | partial unique index `WHERE is_current` |
| authored by a real person | `created_by` is a non-null FK to `users`; a system actor is refused with `user_actor_required` |

Creating a version writes **two** audit entries: one against the version, and one
against the influencer, so the character's own history tab shows that its identity
moved.

### VoiceProfile **[step 3]**

`id`, `influencer_id`, `version_number`, `provider`, `provider_voice_id`,
`language`, `accent`, `pace_wpm`, `pronunciation_dictionary`,
`commercial_usage_confirmed`, `status`, `created_at`.

Versioned like the Character Bible. `commercial_usage_confirmed` must be recorded
before a profile can be used: the platform does not clone voices without a
confirmation of rights on file.

---

## Assets **[step 3]**

### Asset

`id`, `organization_id`, `influencer_id?`, `asset_type`, `storage_key`,
`mime_type`, `width?`, `height?`, `duration_ms?`, `sha256`, `status`, `metadata`,
`created_at`.

`asset_type` ∈ `reference_image | golden_reference | generated_image |
source_video | generated_video | audio | subtitle | thumbnail | workflow_file |
lora_file`.
`status` ∈ `uploaded | processing | ready | failed | archived`.

`sha256` is computed server-side on ingestion, so an output can always be matched
back to the bytes that were produced.

### AssetVersion

`id`, `asset_id`, `version_number`, `parent_asset_version_id?`,
`generation_job_id?`, `metadata`, `created_at`.

`parent_asset_version_id` and `generation_job_id` are what make lineage answerable:
every generated output points at the job that produced it and the version it derived
from.

---

## Production recipes **[step 4]**

### GenerationRecipe

`id`, `organization_id`, `influencer_id?`, `name`, `recipe_type`, `status`,
`created_at`.
`recipe_type` ∈ `image | image_to_video | text_to_video | tts | lip_sync | montage`.

### GenerationRecipeVersion

`id`, `recipe_id`, `version_number`, `workflow_engine`, `workflow_version`,
`model_name`, `model_version`, `lora_asset_version_id?`, `prompt_template`,
`negative_prompt_template`, `input_schema` (jsonb), `output_schema` (jsonb),
`default_parameters` (jsonb), `estimated_cost_cents?`, `created_at`, `is_current`.

Immutable, same rules as `InfluencerVersion`. `input_schema` is what the worker
validates runtime inputs against — a prompt never becomes arbitrary workflow JSON
([ADR-0004](adr/0004-comfyui-adapter.md)).

---

## Content factory **[step 5]**

### ContentBrief

`id`, `organization_id`, `influencer_id`, `title`, `status`, `platform`, `pillar`,
`format`, `target_audience`, `hook`, `core_message`, `call_to_action`,
`disclosure_required`, `advertising_disclosure_required`, `risk_level`,
`experiment_id?`, `created_by`, `created_at`, `updated_at`.

`pillar` ∈ `reach | trust | conversion`. `risk_level` ∈ `low | medium | high`.

#### State machine

```
draft ──► brief_ready ──► script_ready ──► generating ──┬──► awaiting_review
                              ▲                          │
                              │                          └──► qa_failed
                    qa_failed ┘                                  │
                                                                 ▼
        awaiting_review ──► approved ──► scheduled ──► published ──► analyzed
              │  └──► rejected
              └──► qa_failed
```

| From | Allowed to |
|---|---|
| `draft` | `brief_ready` |
| `brief_ready` | `script_ready` |
| `script_ready` | `generating` |
| `generating` | `qa_failed`, `awaiting_review` |
| `qa_failed` | `script_ready`, `generating` |
| `awaiting_review` | `approved`, `rejected`, `qa_failed` |
| `approved` | `scheduled` |
| `scheduled` | `published` |
| `published` | `analyzed` |
| `analyzed`, `rejected` | — |

Forbidden, and asserted by tests when built:

- `published → anything` (publication is a fact, not a state to revise)
- `draft → published`
- `generating → approved` (QA cannot be skipped)
- **any transition to `scheduled` without an approved `ApprovalTask`**

Implemented as a backend domain service on `app.core.state_machine.StateMachine` —
the same primitive the influencer lifecycle already uses. Frontend button visibility
is a convenience, never the enforcement point.

### ContentScriptVersion

`id`, `content_brief_id`, `version_number`, `spoken_text`, `on_screen_text`,
`caption`, `hashtags` (jsonb), `cta`, `language`, `created_by`, `created_at`,
`is_current`. Append-only.

---

## Generation **[step 6]**

### GenerationJob

`id`, `organization_id`, `content_brief_id`, `recipe_version_id`, `status`,
`input_payload`, `output_payload`, `idempotency_key`, `external_job_id?`,
`started_at?`, `completed_at?`, `error_code?`, `error_message?`,
`estimated_cost_cents?`, `actual_cost_cents?`, `created_at`, `updated_at`.

`status` ∈ `queued | preparing | running | succeeded | failed | cancelled`.

`idempotency_key` is unique per organization and is also the ARQ job id, so a
repeated submission is a no-op at both layers rather than a duplicate paid
generation. Every external side effect on this platform carries one.

---

## QA and approval **[step 7]**

### QAReview

`id`, `content_brief_id`, `asset_version_id`, `review_type`, `score?`, `result`,
`findings` (jsonb), `created_by?`, `created_at`.

`review_type` ∈ `technical | identity | lip_sync | brand | policy`.
`result` ∈ `pass | fail | needs_human_review`. `created_by` is nullable because an
automated technical check has no human author — but `needs_human_review` always
routes to a person.

### ApprovalTask

`id`, `content_brief_id`, `status`, `requested_role`, `assigned_user_id?`,
`decision_notes?`, `decided_by?`, `decided_at?`, `created_at`.

`status` ∈ `pending | approved | rejected | revision_requested | escalated`.

The gate in front of scheduling. `requested_role` records who was *asked*;
`decided_by` records who actually decided. High-risk briefs require
`approval:decide_high_risk`, held only by `compliance` and `owner`.
See [ADR-0003](adr/0003-human-approval-gate.md).

---

## Publication and analysis **[step 8]**

### ContentPublicationPlan

`id`, `content_brief_id`, `platform`, `target_account_id?`, `scheduled_at?`,
`timezone`, `publication_status`, `caption_snapshot`, `disclosure_snapshot`,
`external_post_id?`, `created_at`, `updated_at`.

`publication_status` ∈ `draft | scheduled | ready_for_manual_publish | published |
failed`.

`caption_snapshot` and `disclosure_snapshot` are copies taken at approval time, not
references. That is what makes an approval meaningful: the reviewer approved
*specific text*, and later edits to the script or the policy cannot rewrite it.

On the MVP there is no automatic publishing. The terminal automated state is
`ready_for_manual_publish`; a human publishes and marks the result.

### Experiment

`id`, `organization_id`, `name`, `hypothesis`, `status`, `primary_metric`,
`guardrail_metrics` (jsonb), `start_at?`, `end_at?`, `created_at`.

---

## Audit **[built]**

### AuditLog

`id`, `sequence_number`, `organization_id`, `actor_type`, `actor_id?`, `action`,
`entity_type`, `entity_id`, `before_data?`, `after_data?`, `request_id?`,
`created_at`.

`actor_type` ∈ `user | system | agent`. An `agent`-role actor is recorded as
`agent`, never `user`, so automated activity stays distinguishable in the trail
permanently — not just while its token lives.

`action` is a closed set (`app/shared/events/actions.py`), because free-text action
names drift (`influencer.update` vs `influencer_updated`) and make the log
unqueryable.

Append-only: no `updated_at`, no update path, no delete endpoint, and the repository
exposes only `list_entries` and `count_entries` (asserted by a test).

`sequence_number` is a `BIGINT IDENTITY` and is the ordering column.
`created_at` cannot order the log: PostgreSQL's `now()` is the *transaction*
timestamp, so every row written by one request shares it.

Written by `AuditService` inside the caller's transaction — see
[ADR-0007](adr/0007-audit-log-in-transaction.md).
