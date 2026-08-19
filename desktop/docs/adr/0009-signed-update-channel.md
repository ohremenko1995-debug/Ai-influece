# ADR-0009 — A signed update channel, and a database that survives it

- **Status:** accepted
- **Date:** 2026-08-19

## Context

A desktop application without automatic updates stops being maintained: users stay on
whatever version they installed, and a platform API change breaks them permanently with no
way to reach them.

An update mechanism is also the most dangerous code in the product. It downloads an
executable and runs it with the user's privileges. If an attacker can substitute the
download, they own the machine — and this application holds credentials that publish to a
public audience.

There is a second risk that has nothing to do with attackers. An update carries schema
migrations, and the database it migrates is the user's only copy of their work. A migration
that fails halfway on a server is an incident with a backup and a DBA. On a desktop it is
someone's characters, approvals and publication history.

## Decision

**Signed artefacts, verified before install, distributed through GitHub Releases behind an
endpoint abstraction — and a database backup before any migration runs.**

### Signing

Every release publishes:

| Artefact                       | Purpose                                        |
| ------------------------------ | ---------------------------------------------- |
| `InfluencerOS-x.y.z-setup.exe` | signed NSIS installer                          |
| Tauri update bundle            | the same build, as the updater consumes it     |
| updater signature              | verified by the updater before installing      |
| `latest.json`                  | version, notes, per-platform URL and signature |
| checksums                      | published alongside                            |
| SBOM                           | desirable, not blocking                        |

The updater verifies the signature **before** installing. An unsigned or mismatched artefact
is refused, not warned about.

**The private signing key exists only in CI secrets or protected storage. It is never in the
repository, never in a build log, never in an environment variable printed by a workflow.**

### Channels

`stable` by default, `beta` opt-in. Auto-check is on by default because a user who has to
remember to check will not.

### Behaviour

- Download and install require a visible, understandable UI. Nothing is installed silently.
- The user can choose "Install" or "Remind me later".
- **No forced updates in the first version.** A product that can push code onto a machine
  without consent has to earn that trust first.
- The application restarts after installing.
- `DATA_ROOT` is never touched. This is why it must live outside any directory the updater
  replaces ([ADR-0004](0004-managed-local-media-library.md)).

### Migrations

1. **Back up the database file before running migrations.** A file copy into
   `<DATA_ROOT>/backups/`, with the version it came from in the name.
2. Run migrations.
3. On failure: **do not continue on a partially changed schema.** Restore the backup and
   start the previous version, or enter a recovery mode that explains what happened and where
   the backup is.

Every schema change ships with a working `downgrade` and a test that upgrades, downgrades and
upgrades again ([ADR-0003](0003-sqlite-local-postgresql-cloud.md)). A downgrade that has
never been executed is not a rollback plan.

### Release gates

A release tag builds on a clean Windows runner and publishes only after all of:

```text
build sidecar → bundle ffprobe → build Tauri NSIS → sign updater artifacts
→ generate latest.json → install smoke → first-launch smoke
→ upgrade-from-previous-stable smoke
```

The upgrade smoke test is the one that matters most: it is the only check that proves an
existing user's data survives.

### Future update server

The updater reads a manifest URL. Replacing GitHub's static JSON with an own HTTPS endpoint
must not change the update experience, so the endpoint is configuration behind an
abstraction from the start — while the running product uses GitHub Releases, because that is
what exists.

## Consequences

**Gained**

- Users can be reached with a fix when a platform API changes.
- A substituted download is refused rather than installed.
- A user's work survives an update, provably, because a gate tests exactly that.
- A failed migration is recoverable by the application instead of by a support conversation.
- Distribution can move off GitHub without changing the client's behaviour.

**Given up**

- **A code-signing certificate is a recurring cost and an operational burden.** It expires, it
  must be renewed, and an EV certificate needs hardware. Without one, SmartScreen warns users
  that the installer is untrusted.
- **Key compromise is catastrophic and slow to recover from.** Rotating a signing key means
  every existing installation must be updated by a key it already trusts, or reinstalled by
  hand.
- **No forced update means old versions stay in the wild.** A broken connector on a version
  nobody upgrades is a support burden with no remote fix.
- **Backups accumulate.** Pre-migration copies of a database grow; retention is another policy
  to get right, and a full disk during an update is its own failure mode.
- **Downgrade paths must be maintained for real.** Writing a `downgrade` that has never run is
  self-deception, so migration tests cost real effort on every schema change.

## Alternatives considered

| Alternative                            | Why not                                                                                                                                        |
| -------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------- |
| No auto-update, manual downloads       | Users stay on old versions forever, and a platform API change becomes permanent breakage.                                                      |
| Unsigned updates over HTTPS            | TLS authenticates the host, not the artefact. A compromised release, a hijacked bucket or a mirror substitutes a binary that installs cleanly. |
| Microsoft Store distribution           | Sandboxing constrains the sidecar and the data root, certification is slow, and it forecloses direct distribution and the beta channel.        |
| Forced silent updates                  | Restarting an application mid-work, or changing behaviour without consent, on a machine holding publishing credentials.                        |
| Migrate first, back up only on failure | By the time a migration fails there may be nothing left to back up.                                                                            |
| Own update server from day one         | Infrastructure to build, host and secure before there is a single user. GitHub Releases is signed, free and already gated by CI.               |
