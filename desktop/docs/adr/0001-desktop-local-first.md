# ADR-0001 — Desktop local-first architecture

- **Status:** accepted
- **Date:** 2026-08-19

## Context

The donor is a server product: PostgreSQL, Redis, MinIO, Docker Compose, six containers.
That is the right shape for a team operating a platform. It is the wrong shape for this
product, and the gap is not a matter of taste.

The user is one person on one Windows PC. They asked for an application, not a deployment.
The material they manage — character identities, approved photos and videos, connected
social accounts — is theirs, sits on their disk, and has no reason to leave it. The
credentials involved can publish to a public audience under a real brand.

Two constraints came with the requirement rather than being chosen:

- **Windows 10/11, x64.** Not "cross-platform, Windows first".
- **The application must install and run with no Docker, Python, Node, PostgreSQL or
  Redis on the machine.** A user who has to install a database has not received an
  application.

There is also a stated future: a small team, then a commercial product with a cloud
scheduler that publishes while the computer is off. Whatever is built now must not have to
be thrown away then.

## Decision

**The application is local-first. The local installation is complete and authoritative;
cloud is an optional extension, never a dependency.**

Concretely:

1. **One installer, no prerequisites.** Everything the application needs — the Python
   sidecar, `ffprobe.exe`, the web assets — is bundled in the signed installer. Nothing is
   downloaded on first run and nothing is expected to be present.
2. **All state is local.** SQLite for data
   ([ADR-0003](0003-sqlite-local-postgresql-cloud.md)), a managed directory for media
   ([ADR-0004](0004-managed-local-media-library.md)), Windows Credential Manager for
   secrets ([ADR-0008](0008-windows-secure-secret-storage.md)).
3. **No broker, no external queue.** Background work is a loop over a jobs table in the
   same SQLite database, claimed with a lease.
4. **The user chooses `DATA_ROOT`.** The application does not decide where a person's work
   lives, and it never writes into `Program Files`.
5. **Every remote capability is a connector behind an interface**, off by default, and
   absent from the running product until there is a service behind it
   ([ADR-0010](0010-optional-media-relay-and-cloud-scheduler.md)).
6. **The domain stays portable.** Services must not depend on SQLite specifics, so the same
   domain can run against PostgreSQL in a cloud deployment later.

Offline is the normal case, not a degraded mode. The only operations that require the
network are the ones that inherently do: publishing, testing a connection, calling an LLM,
and checking for updates.

## Consequences

**Gained**

- The product is installable by its actual user. This is the whole point.
- No operational surface: nothing to configure, no ports to open, no service to keep
  running, no container to update.
- The user's media and their Character Bible never leave the machine unless they
  deliberately publish or explicitly enable the relay.
- Development stays fast: the test suite runs against a file, so there is no fixture
  database to provision.

**Given up**

- **No concurrent multi-user access.** SQLite with WAL supports one writer. The roles and
  permissions survive for the team version, but two people cannot use one installation at
  once.
- **Publishing requires the computer to be on.** A missed slot is executed late on the next
  start, and marked as late ([ADR-0005](0005-human-approval-before-automatic-publishing.md)).
  The honest fix is the cloud scheduler, which is a later stage.
- **We own the packaging problem.** Bundling a Python interpreter, keeping the installer
  signed, and testing upgrades on a clean Windows image are real recurring costs that a
  web deployment would not have.
- **No central backup.** If the user's disk dies, their work is gone. The application backs
  up the database before migrations; a general backup story is theirs.
- **Platform-specific work.** Credential Manager, NSIS, code signing and tray behaviour are
  Windows APIs. A macOS port would need its own equivalents.

## Alternatives considered

| Alternative                                  | Why not                                                                                                                                                                                            |
| -------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Ship the donor as-is with Docker Desktop     | Requires Docker on the user's machine, a licence check for commercial use, virtualisation enabled in BIOS, and ~2 GB of images. The user asked for an application.                                 |
| Cloud-first SaaS, thin desktop client        | Would mean uploading every photo and video, and every character identity, to a server before anything works. Unacceptable for the material, and it makes the product useless without a connection. |
| Embed PostgreSQL in the installer            | Possible, and roughly 300 MB plus a service to supervise, a data directory to migrate and a port to defend — to serve one writer.                                                                  |
| Electron with a Node backend                 | Would mean rewriting the donor's Python domain in TypeScript. The domain is the asset being reused.                                                                                                |
| Local-only, with cloud declared out of scope | The cloud scheduler is a stated product direction. Designing without those seams means a rewrite later; designing with them costs a few interfaces now.                                            |
