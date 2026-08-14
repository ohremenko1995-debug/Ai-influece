# ADR-0006 — Stateless JWTs, with a doubly-fenced development login stub

- **Status:** accepted
- **Date:** 2026-08-14

## Context

MVP step 1 requires "an authentication stub for development". A local developer should
not need a password to switch between the seven seeded roles while building screens.

That convenience is also a hole: a passwordless login endpoint reachable in a deployed
environment is a full compromise. The gate must not be a single environment variable
somebody can flip.

Separately, the session mechanism itself needs deciding. The platform is an internal
tool for a small team, but it holds production identity and approval records.

## Decision

### Stateless HS256 JWTs, access plus refresh

| Token   | TTL    | Claims                                            |
| ------- | ------ | ------------------------------------------------- |
| access  | 30 min | `sub`, `typ=access`, `iat`, `exp`, `jti`, `org?`  |
| refresh | 7 days | `sub`, `typ=refresh`, `iat`, `exp`, `jti`, `org?` |

No session table. Chosen for the MVP because the alternative costs a database read on
every request plus a revocation store, to protect a small internal team — and the two
mitigations below cover the realistic risk.

`typ` is verified on decode, so a refresh token cannot be presented as an access
token. The algorithm list is fixed at `["HS256"]`, so `alg: none` and asymmetric
confusion attacks are rejected. Required claims are declared, so a token without `exp`
is invalid rather than eternal.

The `org` claim is a _hint_, not an authorization. `get_current_actor` re-loads the
user and the membership on every request, so:

- setting `User.status = disabled` blocks the **next** request, without revocation;
- revoking a membership takes effect immediately;
- a role change takes effect immediately.

That is what makes a 30-minute access TTL acceptable: the token proves who you are,
never what you may do.

### Key length is enforced

HMAC-SHA256 keys shorter than the 32-byte digest size are cryptographically weak
(RFC 7518 §3.2) and PyJWT warns about them. `Settings.validate_production_safety`
rejects a short key outside development, and the development placeholder is long enough
not to warn — a warning that fires constantly is a warning nobody reads.

### The development stub is fenced twice, independently

`POST /api/v1/auth/dev-login` takes an email and returns tokens.

```python
@property
def dev_auth_active(self) -> bool:
    return self.dev_auth_enabled and self.environment is Environment.DEVELOPMENT
```

1. **The route is not registered** unless `dev_auth_active` — `build_auth_router`
   omits it, so in staging the path returns 404 and never appears in the OpenAPI
   document.
2. **The service refuses the call** under the same condition, so the handler is safe
   even if it were ever mounted unconditionally.

And a third, coarser barrier: `validate_production_safety` refuses to boot a
non-development environment with `DEV_AUTH_ENABLED=true` at all.

Two conditions, from two different variables, at two layers. Flipping
`DEV_AUTH_ENABLED` in staging does not open a passwordless login — it stops the process
from starting.

Verified by tests: the route works in development, is absent from a
production-configured app's OpenAPI paths, and `dev_auth_active` is false for every
combination except `development` + `true`.

### Real password login exists alongside it

The stub is a convenience, not the mechanism. `POST /auth/login` uses argon2id with a
constant-cost verification against a dummy hash when the address is unknown, so
response timing does not reveal whether an account exists, and both cases return the
identical message.

`password_hash` is nullable: an invited user has no credential yet, and an SSO-backed
account never will.

## Consequences

**Gained**

- Switching roles locally is one HTTP call, which makes building and reviewing
  role-dependent UI fast.
- No session table, no revocation store, no read amplification per request.
- A disabled user or revoked membership takes effect on the next request despite the
  token being stateless.

**Given up — stated plainly**

- **No revocation.** A leaked access token is valid for up to 30 minutes, a refresh
  token for up to 7 days. There is no logout-everywhere.
- **No rate limiting** on `/auth/login`. Failed attempts against known accounts are
  audited, so brute force is _visible_, but it is not blocked.
- **No MFA or SSO.**
- Rotating `SECRET_KEY` invalidates every session at once — the only revocation
  mechanism available, and a blunt one.

### The intended fix, when it is needed

A `sessions` table keyed by `jti`, with `revoked_at`, checked on refresh (cheap:
refresh is rare) and optionally on access. That buys logout-everywhere and per-device
revocation for one indexed read. Deferred because the MVP's user population is a
handful of known accounts on an internal tool.

## Alternatives considered

| Alternative                         | Why not                                                                                                                                                                                            |
| ----------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Server-side sessions from the start | A database read per request and a revocation store, before there is a user population that needs it. Easy to add later behind the same `TokenClaims` boundary.                                     |
| A single shared dev token in `.env` | Cannot represent seven roles, and a hardcoded credential in a file is exactly the thing that leaks into a deployed environment.                                                                    |
| `if DEBUG` around the stub          | One variable, one layer. The failure mode — a passwordless login in production — is severe enough to justify two independent conditions and a boot-time refusal.                                   |
| Auth0 / Clerk / an external IdP     | Sensible for a product with external users. For an internal tool it adds an external dependency and a network hop to log in, and does not remove the need for the local role-switching affordance. |
| Asymmetric RS256                    | Useful when a separate service must verify tokens without the signing key. There is one verifier here (the API), so HS256 is simpler with no loss.                                                 |
