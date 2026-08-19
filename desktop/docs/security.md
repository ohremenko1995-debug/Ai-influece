# Security and privacy policy

> **Stage 0.** This document states the policy the stages implement. Nothing in it runs
> yet. [IMPLEMENTATION_STATUS.md](../IMPLEMENTATION_STATUS.md) is the record of what
> exists.

The threat model is not a server's. This application runs on a machine we do not control,
ships to people we cannot audit, and holds credentials that can publish to a real audience
under a real brand. Three things follow: a compromise of the local machine is partly out
of scope and must be said so plainly, a stolen credential must not be recoverable from
anything we write to disk, and a mistake must not be publishable.

---

## Authentication

| Item             | Decision                                                                  |
| ---------------- | ------------------------------------------------------------------------- |
| Method           | email + password, inherited from the donor                                |
| Password storage | Argon2id hash only. The plaintext is never stored, logged or transmitted. |
| First user       | created by the first-run wizard, gets `owner`                             |
| "Remember me"    | the refresh session may be stored in Windows Credential Manager           |
| Logout           | deletes the local refresh session                                         |
| Manual lock      | available from the tray, so an unattended machine can be locked           |

The donor's development authentication stub is **not** ported. An environment-variable
bypass is acceptable in a container that only ever runs on a developer's laptop; it is not
acceptable in a signed binary on an end user's desktop.

## Authorization

Permission-based, checked at the route and again in the service. Roles are retained in
full — `owner`, `creative_lead`, `operator`, `reviewer`, `compliance`, `analyst`, `agent` —
even though the first version is used by one person, because removing them would make the
team version a rewrite.

The `agent` role stays fenced by subtraction from the matrix, independently of what the
matrix grants. An automated actor may draft LLM text. It may not:

- connect a social account
- acknowledge a validation warning
- approve a publication
- change platform settings after approval
- schedule
- publish
- enable the media relay

## Local transport

The sidecar binds `127.0.0.1` on an OS-assigned port and requires two things on every
protected route: a desktop session header the Rust shell adds, and a user auth session.

The desktop session secret is generated per launch, kept in memory, and passed to the
sidecar through the process environment or an inherited IPC channel. It is never written to
disk, never logged, and never handed to JavaScript.

**Known limitation, stated deliberately:** another process running as the same Windows user
can read that process's environment. The desktop session is a boundary against _other
origins_ — a page in a browser, another application talking to localhost — not against a
process that already has the user's privileges. Protecting against the latter is the
operating system's job, and claiming otherwise would be dishonest.

---

## Secrets

The rule, without exceptions:

> API keys and OAuth tokens are never stored in SQLite, JSON, `.env`, frontend storage or
> logs. The database holds only a `secret_ref`.

| Concern                   | Decision                                                                                          |
| ------------------------- | ------------------------------------------------------------------------------------------------- |
| Store                     | Windows Credential Manager (DPAPI), bound to the current Windows user                             |
| Reference                 | the database holds an opaque `secret_ref` and nothing derived from the secret                     |
| Retrieval                 | `secure_secret_get_for_backend` hands the value to the sidecar; it never returns it to JavaScript |
| OAuth `state`             | single-use, with a TTL                                                                            |
| PKCE                      | used wherever the platform supports it                                                            |
| Refresh token rotation    | used wherever the provider supports it                                                            |
| OAuth surface             | the system browser, never an embedded WebView                                                     |
| Social passwords          | never requested, never stored, no scraping, no browser automation                                 |
| Disconnect                | revoke at the platform first, then delete the local secret                                        |
| Disconnect, revoke failed | warn, and still allow local deletion after an explicit confirmation                               |

Logs redact `Authorization` headers, cookies, tokens and provider payloads. There are no
secrets in `.env.example`, fixtures, snapshots or OpenAPI examples — not even
plausible-looking ones, because a plausible-looking key in an example is indistinguishable
from a real one that was committed by mistake.

See [ADR-0008](adr/0008-windows-secure-secret-storage.md).

---

## Privacy

### Media and the LLM

`include_media` is **off by default**, per connection. The toggle appears only when the
provider and model support vision. Before the first send, the user sees an explicit notice
saying what will leave the machine. The decision can be remembered per connection, and the
default stays off for the next one.

Whether an image was sent is recorded on the generation record. The image itself never
enters telemetry or logs. ([ADR-0007](adr/0007-llm-provider-boundary.md))

### The media relay

Off by default. It exists only for platforms that ingest media by public URL. When it is
used, the UI names the exact file that will be uploaded, the URL is unpredictable, the TTL
is bounded, and the file is deleted after publication or expiry. Only the one selected
final file is ever sent. ([ADR-0010](adr/0010-optional-media-relay-and-cloud-scheduler.md))

### Telemetry

Off by default. Crash upload off by default. Local structured logs on, with automatic
rotation.

An opt-in report may contain only: application version, OS version, an anonymised error
code, a request id, a redacted stack trace, the connector type, and the migration version.
The user sees a preview of the exact report before it is sent.

It may never contain post text, Character Bible or Voice Profile content, media, handles
without separate confirmation, API keys or tokens, or a full provider response.

A diagnostics bundle excludes the database, the media library and all secrets by default.

---

## Audit

Every consequential action writes an audit row in the same transaction as the change.
Audited, at minimum:

- login, logout, and failed login attempts
- character creation and modification
- a new Character Bible or Voice Profile version
- media import and archival
- acknowledgement of a validation warning
- connecting, disabling, reconnecting and disconnecting a social account
- creating and modifying a publication preset
- an LLM generation and the variant chosen
- approval and revision requests
- schedule, reschedule and cancel
- every publish attempt and its result
- changes to privacy, relay or telemetry settings
- application updates and database migrations

Audit rows never contain secrets, access tokens, refresh tokens, API keys or a full
external provider response.

---

## Transparency obligations

The characters this application publishes are openly virtual, and the product is built to
keep them that way.

- A character carries a disclosure policy, and the disclosure text is part of the approval
  snapshot hash — so changing it after approval voids the approval rather than slipping
  through.
- No feature exists, or will be added, whose purpose is to hide that content is synthetic,
  to impersonate a real person, or to clone a voice without a recorded confirmation.
- No provenance fields for generated media exist, because no media is generated here
  ([ADR-0011](adr/0011-no-media-generation.md)). The application is not a laundering step
  between a generator and a platform: what it publishes is what the user imported and
  approved.

---

## Update integrity

Update artefacts are signed, and the updater verifies the signature before installing
([ADR-0009](adr/0009-signed-update-channel.md)). The private signing key lives only in CI
secrets and never in the repository. The database is backed up before migrations run; a
failed migration restores the backup and starts the previous version rather than
continuing on a half-changed schema.
