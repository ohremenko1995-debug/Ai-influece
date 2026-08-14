# Security

Scope: what is implemented and verified today, what is deliberately deferred, and
what a reader must not assume works.

---

## Authentication

Email and password, argon2id hashing, stateless HS256 JWTs.

| Property | Value |
|---|---|
| Password hash | argon2id via `argon2-cffi` (RFC 9106 defaults) |
| Access token TTL | 30 minutes (`ACCESS_TOKEN_TTL_MINUTES`) |
| Refresh token TTL | 7 days (`REFRESH_TOKEN_TTL_MINUTES`) |
| Signing | HS256, key ≥32 bytes |
| Required claims | `sub`, `iat`, `exp`, `jti`, `typ`, optional `org` |

Implemented protections:

- **Token type confusion is rejected.** The `typ` claim is checked on decode, so a
  refresh token presented as an access token fails with `token_wrong_type`.
- **`alg: none` and foreign-key signatures are rejected** — the algorithm list is
  fixed at `["HS256"]`.
- **User enumeration is limited.** A login for an unknown address still performs an
  argon2 verification against a constant dummy hash, and both the unknown-address
  and wrong-password cases return the identical message *"Email or password is
  incorrect"*.
- **Only `active` users authenticate.** `invited`, `suspended` and `disabled` are
  refused with `account_inactive`.
- **Password hashes are re-hashed transparently** when argon2 parameters change.
- **Credential material never leaves the process.** `password_hash` is absent from
  every response model, and the audit snapshot writes `[redacted]` in its place —
  visible as *changed*, never as a value.
- **Short signing keys are surfaced, not silenced.** PyJWT warns below 32 bytes
  (RFC 7518 §3.2); the development placeholder is deliberately long enough not to
  warn, and non-development environments refuse to boot with a short key.

### Known gap: no revocation

There is no server-side session store on the MVP. A leaked access token remains
valid until it expires, and a refresh token for up to 7 days. Mitigations in place:
a short access TTL, and `status` on `User` — flipping a user to `disabled` blocks
the *next* request, because `get_current_actor` re-loads the user and the membership
on every call rather than trusting the token's contents.

A `sessions` table with a `jti` denylist is the intended fix and is recorded in
[ADR-0006](adr/0006-development-auth-stub.md).

### The development login stub

`POST /api/v1/auth/dev-login` is passwordless. It is fenced twice:

1. The route is only added to the router when `Settings.dev_auth_active` is true.
2. `AuthService.dev_login` raises `dev_auth_disabled` under the same condition.

`dev_auth_active` requires **both** `DEV_AUTH_ENABLED=true` **and**
`ENVIRONMENT=development`, so changing a single environment variable in staging
cannot open a passwordless login. A test asserts the path is absent from the OpenAPI
document of a production-configured app, and `Settings.validate_production_safety`
refuses to boot a non-development environment with the flag on.

---

## Authorization

Endpoints depend on **permissions**, never on roles. Reshaping a role is a change to
`app/shared/permissions/matrix.py` alone and cannot silently widen an endpoint.

Checks happen twice, on purpose:

| Layer | Purpose |
|---|---|
| `RequirePermission(...)` route dependency | fails before the handler body; visible in the OpenAPI document |
| `actor.require_permission(...)` in the service | protects every caller, including the worker and the CLI, which never pass through a route |

### Separation of duties

The role that produces content does not approve it.

| Capability | Roles |
|---|---|
| request approval | `owner`, `creative_lead`, `operator`, `reviewer`, `compliance` |
| decide approval (low/medium risk) | `owner`, `reviewer`, `compliance` |
| decide approval (high risk) | `owner`, `compliance` |
| author/modify disclosure policy | `owner`, `compliance` |
| schedule content | `owner`, `creative_lead` |
| connect a social account | `owner` |

`creative_lead` may schedule but may not decide an approval — and scheduling still
requires an approved `ApprovalTask`, so the scheduling permission is not a way past
the gate ([ADR-0003](adr/0003-human-approval-gate.md)).

### The agent fence

An `agent`-role actor must never be able to publish, approve, modify policy, or
connect a social account. This is enforced **twice**:

1. The matrix grants the role only reads plus `content:create`,
   `content:script_create` and `job:create`.
2. `AGENT_FORBIDDEN_PERMISSIONS` is subtracted from whatever the matrix says, inside
   `permissions_for_role` and `role_has_permission`.

The second layer exists so that an editing mistake in the table cannot grant an
automated actor authority. A test proves it: it tampers with the matrix at runtime
to grant `approval:decide_high_risk` to `agent`, then asserts the permission is
still refused.

The fenced set is broader than the four named capabilities — it also excludes
influencer creation/update/archival, Character Bible authorship, voice management,
experiment management, and organization/membership control.

Additionally, `created_by` on a Character Bible version is a non-null foreign key to
`users`, and a system actor is refused with `user_actor_required`. Identity
authorship is not automatable at all.

### Actor types in the trail

`actor_type` ∈ `user | system | agent`. An `agent`-role membership produces
`actor_type=agent`, never `user`, so automated activity stays distinguishable in the
audit log permanently — not only while its token lives.

`CurrentActor.system(...)` holds every permission, because it is not a delegated
human identity. It is unreachable from HTTP: no authentication path constructs one.
Its actions are audited as `system`.

---

## Multi-tenancy

Every production table carries `organization_id`, and every repository query filters
on it. There is no unscoped read by primary key anywhere in the codebase.

- `X-Organization-Id` is a **selector, not a grant**. An active `Membership` must
  exist; otherwise the request fails with `403 not_a_member`.
- With no header and no `org` claim, a user belonging to several organizations must
  choose (`403 organization_required`) rather than getting an arbitrary default.
- Reading another tenant's entity returns **404, not 403** — the API never confirms
  that a row exists in someone else's organization.
- Cross-tenant references are rejected at the domain layer: assigning another
  organization's disclosure policy to an influencer is a `404`.

Tests cover each of these with a second seeded tenant.

---

## Data protection

| Concern | Handling |
|---|---|
| Passwords | argon2id, never logged, `[redacted]` in audit snapshots |
| Tokens | not persisted; `repr=False` on the request fields |
| Asset storage | private bucket, anonymous access explicitly denied, presigned URLs only (step 3) |
| Presigned URL TTL | 900 s default, capped at 3600 s |
| Secrets in config | `.env.example` holds annotated placeholders only; production values come from the secret manager |
| CORS | explicit origin list; `*` is rejected by a validator |
| Error responses | internal exception text is never returned; 500 responses carry only a code and the request id |
| Validation errors | only `location`, `message`, `type` are copied out — never pydantic's `ctx` (a live exception object) or `input` (the rejected value, possibly a credential) |

### No hard deletes

Production entities are never removed.

| Entity | Retirement |
|---|---|
| `Influencer` | `status=archived` + `archived_at`; terminal and read-only |
| `Membership` | `revoked_at`; the row explains who had access historically |
| `InfluencerVersion` | never retired; superseded by a new version |
| `AuditLog` | append-only; no update or delete path exists |

---

## Audit trail

Every consequential change writes an `AuditLog` row **in the same transaction** as
the change, so an audited change either lands with its evidence or does not land at
all ([ADR-0007](adr/0007-audit-log-in-transaction.md)).

Each row carries the actor (type, id), the action from a closed vocabulary, the
entity type and id, before/after snapshots, and the `request_id` that ties it to the
server logs.

Verified by tests: creation, update, status transition, version creation (two
entries), and policy update all emit; a **refused** action emits nothing; a no-op
update emits nothing.

Ordering uses `sequence_number` (a `BIGINT IDENTITY`), not `created_at`. PostgreSQL's
`now()` is the transaction timestamp, so all rows from one request share it — an
entity history tab ordered by time would show "created" and "updated" in arbitrary
order.

### Known gap: failed logins for unknown addresses

A failed login is audited when the address belongs to a known user with an active
membership — that gives per-tenant brute-force visibility. Attempts against
*unknown* addresses have no organization to file under (`organization_id` is
non-null), so they are logged via structlog only. A separate, non-tenant-scoped
security-events stream is the right home for those.

---

## Transparency and disclosure obligations

The platform is built for **openly virtual** personas, and the model encodes that.

- `DisclosurePolicy` records whether AI disclosure and advertising disclosure are
  required, and the exact text for each.
- An influencer cannot be activated without a disclosure policy assigned.
- An influencer cannot be activated without `adult_representation_confirmed` — an
  explicit record that the character depicts an adult. It is never defaulted to true,
  and it cannot be withdrawn while the character is active.
- A `ContentBrief` carries `disclosure_required` and
  `advertising_disclosure_required` (step 5), and a `ContentPublicationPlan` stores a
  `disclosure_snapshot` taken at approval time — so editing a policy later cannot
  rewrite what a reviewer approved.
- `VoiceProfile.commercial_usage_confirmed` must be recorded before a voice profile
  can be used (step 3).

There are **no** features for hiding the synthetic nature of content, impersonating
identifiable real people, or cloning a voice without a recorded confirmation of
rights. Requests for such features should be refused, not designed around.

---

## Operational hardening notes

- Containers run as a non-root user (`uid 10001`).
- Health probes are unauthenticated and expose no tenant data; `/health/ready`
  actually contacts Postgres, Redis and object storage, so a green readiness check
  means the dependencies answer.
- An inbound `X-Request-ID` is accepted for correlation only, never for
  authorization, and is length-capped at 128 characters so a hostile header cannot
  bloat log lines or audit rows.
- Logging is deliberately cheap on the error path. structlog's default exception
  formatter is rich's, which pretty-prints every frame's locals — one unhandled
  request exception rendered that way was measured at **253 seconds of CPU**. That is
  a self-inflicted denial of service, so module loggers stay lazy and the console
  renderer uses `plain_traceback`.

## Not implemented

Stated so it is not assumed:

| Missing | Consequence |
|---|---|
| Token revocation / session store | a leaked token is valid until expiry |
| Rate limiting on `/auth/login` | brute force is visible in the audit log but not blocked |
| MFA / SSO | password only; `password_hash` is nullable to allow SSO later |
| Database-level immutability triggers | app-level only for version rows |
| Field-level encryption at rest | relies on disk/volume encryption |
| Signed webhooks, IP allowlists | no inbound integrations yet |
| Verified object-storage path | `s3.py` provides the client and probe only; uploads arrive with step 3 |
