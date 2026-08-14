# ADR-0005 — Permission-based RBAC with a hard fence around the agent role

- **Status:** accepted
- **Date:** 2026-08-14

## Context

Seven roles are required: `owner`, `creative_lead`, `operator`, `reviewer`,
`compliance`, `analyst`, `agent`. One of them — `agent` — is an automation identity,
and the platform rules state it must **never** be able to publish, modify policies,
connect social accounts, or approve high-risk content.

A role is held per organization, so the same person can be an operator in one
organization and a reviewer in another. Authorization must therefore be resolved per
`(user, organization)`, never globally.

The specification is explicit that frontend button visibility is not an enforcement
point.

## Decision

### Endpoints depend on permissions, never on roles

43 fine-grained permissions named `<noun>:<verb>` (`influencer:version_create`,
`approval:decide_high_risk`, `calendar:schedule`). A single table maps role →
permission set.

Reshaping a role is a change to `app/shared/permissions/matrix.py` alone. If endpoints
checked roles, adding a role would mean touching every route that should include it —
and forgetting one is a silent authorization hole.

### Every role reads

`READ_PERMISSIONS` is the floor for all seven roles. An internal production tool is
useless if a reviewer cannot see the recipe that produced what they are reviewing.
Writes are what differ.

### Separation of duties

The role that produces content does not approve it:

| Capability                      | Roles                                                |
| ------------------------------- | ---------------------------------------------------- |
| request approval                | owner, creative_lead, operator, reviewer, compliance |
| decide approval                 | owner, reviewer, compliance                          |
| decide **high-risk** approval   | owner, compliance                                    |
| author/modify disclosure policy | owner, compliance                                    |
| schedule content                | owner, creative_lead                                 |
| connect a social account        | owner                                                |

`creative_lead` may schedule but not decide. That is safe because scheduling
independently requires an approved `ApprovalTask`
([ADR-0003](0003-human-approval-gate.md)), so the permission is not a bypass.

`analyst` is read-only plus `audit:read` — the role exists to answer questions, not
to change anything.

### Checked twice, on purpose

| Layer                                              | Purpose                                                                                               |
| -------------------------------------------------- | ----------------------------------------------------------------------------------------------------- |
| `RequirePermission(...)` as a route dependency     | fails before the handler body runs; appears in the generated OpenAPI document                         |
| `actor.require_permission(...)` inside the service | protects every caller, including the worker, the seed CLI and tests, which never pass through a route |

Duplication is deliberate. The route check is a fast guard and documentation; the
service check is the actual boundary.

### The agent fence is a second, independent mechanism

`AGENT_FORBIDDEN_PERMISSIONS` is subtracted from whatever the matrix says:

```python
def permissions_for_role(role: Role) -> frozenset[Permission]:
    granted = ROLE_PERMISSIONS[role]
    if role is Role.AGENT:
        return granted - AGENT_FORBIDDEN_PERMISSIONS
    return granted
```

The matrix already withholds those permissions. The fence exists so that a future
editing mistake in the table cannot grant an automated actor authority — the kind of
mistake that is easy to make and hard to notice in review.

A test proves the fence is load-bearing: it tampers with the matrix at runtime to grant
`approval:decide_high_risk` to `agent`, then asserts the permission is still refused.

The fenced set is broader than the four named capabilities. It also excludes influencer
creation, update and archival, Character Bible authorship, voice management, experiment
management, and organization or membership control. An agent may read production
context, draft content and queue generation jobs — nothing that changes identity,
policy, or what the public sees.

Two further protections work with it:

- An `agent`-role membership produces `actor_type=agent` in the audit trail, never
  `user`, so automated activity stays distinguishable permanently.
- `InfluencerVersion.created_by` is a non-null FK to `users` and a system actor is
  refused, so identity authorship cannot be automated even by a system process.

### The organization header selects, it does not grant

`X-Organization-Id` chooses which membership to act under. An active `Membership` must
exist regardless. A user in several organizations must choose explicitly rather than
receiving an arbitrary default.

### The system actor holds everything, and is unreachable from HTTP

`CurrentActor.system(org)` has all permissions, because it is not a delegated human
identity — it represents the platform acting on its own behalf (workers, migrations,
seeding). No authentication path constructs one, and its actions are audited as
`system`.

## Consequences

**Gained**

- Adding an endpoint means choosing a permission; the matrix decides who gets it.
- The whole security posture is one readable file, asserted by ~40 tests including an
  exhaustive check that every fenced permission is refused to `agent`.
- Requirement 13 ("a user with Agent role cannot publish, approve, change policy or
  connect an account") is verified at the matrix, at the service, and over HTTP.

**Given up**

- 43 permissions is more vocabulary than 7 roles. That is the cost of not having role
  names hard-coded in route handlers.
- Two checks per action, so a permission must be added in two places when a new
  service method appears. A missed service-level check is the residual risk, mitigated
  by every service method starting with `require_permission`.
- No per-resource permissions (e.g. "reviewer for influencer X only"). Not required;
  it would need a policy engine rather than a matrix.

## Alternatives considered

| Alternative                           | Why not                                                                                                                                                                                                                                                    |
| ------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Role checks at endpoints              | Adding a role means editing every route. Silent holes when one is missed.                                                                                                                                                                                  |
| A single `is_admin` flag              | Cannot express separation of duties, which is the point of having reviewer and compliance as distinct roles.                                                                                                                                               |
| Policy engine (OPA, Casbin)           | External dependency and a second language for rules, to express a matrix that fits on one screen. Revisit if per-resource rules ever appear.                                                                                                               |
| Row-level security in PostgreSQL      | Good defence in depth for tenancy, but it cannot express `approval:decide_high_risk`, and it moves authorization away from the code that must explain refusals to users. Repository-level scoping plus 404-on-cross-tenant covers the same ground legibly. |
| Trusting the matrix alone for `agent` | One careless set-union typo would hand an automated actor the ability to approve high-risk content. The fence is cheap; the failure is not.                                                                                                                |
