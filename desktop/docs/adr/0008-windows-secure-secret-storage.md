# ADR-0008 — Secrets live in Windows Credential Manager, never in our data

- **Status:** accepted
- **Date:** 2026-08-19

## Context

The application holds credentials that can publish to a public audience: OAuth access and
refresh tokens for up to nine platforms, bot tokens, and LLM API keys that bill a real card.

A server product would put these in a KMS or a vault. There is neither on a desktop. The
available options are all local, and the naive ones are all bad: a column in SQLite is
readable by anything that can read the file, and a `.env` next to the executable is worse
because backups and support bundles collect it.

There is a second hazard specific to this architecture. The UI is JavaScript in a WebView
([ADR-0002](0002-fastapi-sidecar-inside-tauri.md)). Any secret that passes through
JavaScript is one logging statement, one error report or one careless `console.log` away
from a file on disk.

## Decision

**Windows Credential Manager holds every secret. The database holds only a `secret_ref`.
The value never enters JavaScript.**

### The rule

> API keys and OAuth tokens are never stored in SQLite, JSON, `.env`, frontend storage or
> logs. The database stores an opaque `secret_ref` and nothing derived from the secret.

Secrets are bound to the current Windows user via DPAPI, so another account on the same
machine cannot read them.

### Retrieval path

Three Tauri commands, and the asymmetry between them is the point:

| Command                         | Behaviour                                                                                                           |
| ------------------------------- | ------------------------------------------------------------------------------------------------------------------- |
| `secure_secret_set`             | JavaScript may **write** a secret the user just typed                                                               |
| `secure_secret_get_for_backend` | Rust reads it and hands it to the sidecar over the trusted channel. **It does not return the value to JavaScript.** |
| `secure_secret_delete`          | removes it                                                                                                          |

Writing is unavoidable — the user types an API key into a form. Reading is not: nothing in
the UI needs a secret's value. A connector needs it, and a connector runs in the sidecar.

### Logging

`Authorization` headers, cookies, tokens and provider payloads are redacted at the logging
layer, not at each call site. Redaction that depends on every developer remembering is
redaction that fails. A diagnostics bundle excludes the database, the media library and all
secrets by default.

### OAuth hygiene

- `state` is single-use with a TTL.
- PKCE wherever the platform supports it.
- Refresh token rotation wherever the provider supports it.
- OAuth happens in the system browser
  ([ADR-0006](0006-social-connector-boundary.md)).

### Disconnect

1. Call the platform's revoke endpoint.
2. Delete the local secret.

If revoke fails, **warn and still allow local deletion after an explicit confirmation.** The
alternative — refusing to remove a local secret because a remote call failed — leaves a
credential on disk that the user has asked to be rid of, which is the worse outcome. The
warning says clearly that the token may still be valid at the platform and should be revoked
there.

### What is not protected

Stated plainly rather than implied: **a process running as the same Windows user can ask
Credential Manager for these secrets, and can read the sidecar's environment.** DPAPI binds
to the user, not to our application. This design defends against secrets leaking into files,
backups, logs, diagnostic reports, the database and JavaScript. It does not defend against
malware already running as the user, and no local store can.

## Consequences

**Gained**

- The database can be copied, mailed or attached to a support ticket without leaking a
  credential.
- A stolen `influenceros.db` publishes nothing.
- Another Windows account on the same machine cannot use the credentials.
- The UI cannot leak what it never receives.
- Uninstalling and deleting `DATA_ROOT` leaves credentials that the OS still manages — and
  the disconnect flow is the documented way to remove them.

**Given up**

- **Platform lock-in for this component.** Credential Manager is Windows. A macOS port needs
  Keychain, and the secret layer is the one piece that must be rewritten.
- **No cross-machine portability.** Moving `DATA_ROOT` to another PC keeps the accounts and
  loses their credentials, so every account must be reconnected. Correct, but it will surprise
  people; the UI has to say so.
- **A second store to keep consistent.** A `secret_ref` can point at a secret that no longer
  exists — deleted by hand, or restored from a backup taken on another machine. Every read
  path must handle "reference exists, secret gone" as a reconnect prompt.
- **More moving parts.** Every credential operation crosses the Rust boundary, which is slower
  and harder to test than a column read.

## Alternatives considered

| Alternative                                                 | Why not                                                                                                                                  |
| ----------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| Encrypted column in SQLite                                  | The key has to live somewhere. Next to the database it is decoration; in Credential Manager, the secret might as well be there directly. |
| Secrets in `.env` beside the executable                     | Plain text, collected by every backup and support bundle, and readable by any process.                                                   |
| A master password the user types on each launch             | A password prompt before the scheduler can publish defeats unattended publishing, which is the product.                                  |
| Return secrets to JavaScript and call platforms from the UI | Puts credentials in a WebView and every platform call in the browser's CORS model. Two large problems for no benefit.                    |
| A cloud vault                                               | Requires an account and a network for a local application to function, contradicting [ADR-0001](0001-desktop-local-first.md).            |
| Refuse local deletion when revoke fails                     | Leaves an unwanted credential on the user's disk because a third-party endpoint was down.                                                |
