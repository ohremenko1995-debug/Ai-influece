# Architecture

> **Stage 0.** This document states the architecture the stages implement. Nothing in it
> runs yet. [IMPLEMENTATION_STATUS.md](../IMPLEMENTATION_STATUS.md) is the record of what
> exists.

---

## The shape of the thing

One installer. One process tree. No services to install, no daemon to configure, no
account to create on someone else's machine.

```text
InfluencerOS.exe                          Tauri 2, one instance (single-instance lock)
│
├── WebView                               Next.js App Router, static export
│   └── ApiTransport ──────────────┐      the UI's only door out
│
├── Rust desktop bridge            │      everything that needs the operating system
│   ├── sidecar supervisor         │
│   ├── API proxy ─────────────────┤
│   ├── file picker + file grants  │
│   ├── Credential Manager access  │
│   ├── system tray                │
│   ├── OS notifications           │
│   └── updater                    │
│                                  │
└── influenceros-local-api.exe ◄───┘      FastAPI sidecar, 127.0.0.1, ephemeral port
    ├── SQLite (WAL, foreign_keys=ON)
    ├── managed media library
    ├── validation engine (Pillow, bundled ffprobe.exe)
    ├── publication scheduler
    ├── social connectors
    ├── LLM connectors
    └── audit log
```

Three languages, three jobs, and the division between them is not negotiable:

| Layer      | Owns                                                                                             | Must never own                       |
| ---------- | ------------------------------------------------------------------------------------------------ | ------------------------------------ |
| TypeScript | rendering, navigation, form state, i18n                                                          | a domain rule, a permission decision |
| Rust       | process lifecycle, tray, file dialogs, secrets, updater, notifications, the proxy to the sidecar | any part of the domain               |
| Python     | the domain: entities, versions, validation, approval, scheduling, connectors, audit              | direct OS integration                |

Rewriting the domain in Rust is explicitly out of scope
([ADR-0002](adr/0002-fastapi-sidecar-inside-tauri.md)). The donor's Python domain is the
asset being reused; a rewrite would discard it and buy nothing a desktop user can see.

---

## How the UI reaches the API

The frontend never talks to a port. It calls one Tauri command, and Rust does the rest.

```text
1.  Tauri generates a random session secret in memory.
2.  Tauri starts the sidecar on 127.0.0.1 with an OS-assigned free port.
3.  The secret reaches the sidecar through the process environment or an inherited
    IPC channel — never through a file on disk.
4.  The sidecar prints a readiness handshake naming the port it bound.
5.  The UI calls the Tauri command `api_request`.
6.  Rust adds `X-Desktop-Session` and forwards the request to the sidecar.
7.  The sidecar requires both a valid desktop session and a user auth session for
    every protected route.
```

Two independent checks, because they answer different questions. The desktop session
proves _this request came from our shell_, which is what stops any other local process —
or a page in a browser on the same machine — from driving the API. The user session proves
_who is asking_, which is what the permission matrix needs.

The frontend depends on an interface, not on that mechanism:

```ts
interface ApiTransport {
  request<TResponse>(request: ApiRequest): Promise<TResponse>;
}
```

| Implementation          | Used by                   |
| ----------------------- | ------------------------- |
| `DesktopLocalTransport` | the shipped application   |
| `RemoteCloudTransport`  | the future HTTPS backend  |
| `MockTransport`         | Storybook, frontend tests |

This is the whole reason a cloud version can exist later without rewriting screens
([ADR-0003](adr/0003-sqlite-local-postgresql-cloud.md)). A component that calls `fetch`
directly breaks it, which is why that is forbidden rather than discouraged.

---

## Backend layering

Inherited from the donor unchanged, because the reasons that produced it have not changed.

```text
app/
  api/       HTTP layer: dependencies, versioned routers, readiness
  core/      settings, errors, security, state machine, acting identity
  modules/   one package per bounded context
  shared/    db, storage, scheduler, permissions, connectors, observability
```

`router → service → repository → models`, with four rules:

1. **Routers contain no rules.** They resolve dependencies, check a permission, call a
   service, and shape a response.
2. **Services own the rules, the authorization and the audit emission.** Every service
   method starts by requiring a permission.
3. **Repositories own queries and never authorize.** Every query is scoped by
   `organization_id`.
4. **Services never commit.** The request-scoped unit of work does, which is what keeps a
   change and its audit row in one transaction.

### Transactions

One request, one transaction. The session dependency commits on a clean return and rolls
back on any exception. A service that commits mid-flight would let a change land without
its audit row, so the ability to commit is simply not available to it.

The scheduler follows the same discipline: one job execution is one unit of work, and the
publish attempt record, the target status change and the audit row land together or not at
all.

### The scheduler

A loop inside the sidecar, over a jobs table in SQLite. No broker
([ADR-0001](adr/0001-desktop-local-first.md)).

- Jobs are claimed with a lease, so two loops cannot process one job twice.
- Every external call carries an idempotency key, so a retry after a lost response cannot
  create a second post.
- Times are stored in UTC and rendered in the user's timezone.
- Closing the window does not stop it. Quitting from the tray does.
- At start-up, `scheduled` jobs whose time has passed become `late_pending`, are
  re-validated against their approval, executed, and reported as late
  ([ADR-0005](adr/0005-human-approval-before-automatic-publishing.md)).

### Connectors

The publication domain knows nothing about Instagram or TikTok. It calls
`SocialConnector`, and every platform-specific field arrives through a manifest with a
JSON Schema ([ADR-0006](adr/0006-social-connector-boundary.md)). LLM providers sit behind
the same kind of boundary ([ADR-0007](adr/0007-llm-provider-boundary.md)), with prompt
assembly deliberately outside the adapter so that persona construction cannot drift per
vendor.

---

## Data

`DATA_ROOT` is chosen by the user and is never inside a directory the updater replaces
([ADR-0004](adr/0004-managed-local-media-library.md)).

```text
<DATA_ROOT>/
├── database/influenceros.db
├── media/originals/
├── media/thumbnails/
├── attachments/
├── cache/
├── exports/
├── logs/
├── backups/
└── config/app.json
```

The database stores paths relative to `DATA_ROOT`, so moving the folder does not
invalidate every asset. Imports go through a staging file and an atomic rename, and the
user's original file is never touched.

Secrets are not here. They live in Windows Credential Manager; the database holds only a
`secret_ref` ([ADR-0008](adr/0008-windows-secure-secret-storage.md)).

---

## Deployment

| Artefact                       | Contains                                       |
| ------------------------------ | ---------------------------------------------- |
| `InfluencerOS-x.y.z-setup.exe` | NSIS installer, signed                         |
| Tauri update bundle            | the same build, plus an updater signature      |
| `latest.json`                  | version, notes, per-platform URL and signature |

Distribution is GitHub Releases first, behind an endpoint abstraction so it can move to an
own server without changing the update experience
([ADR-0009](adr/0009-signed-update-channel.md)). Updates never touch `DATA_ROOT`, and the
database is backed up before any migration runs.

Two optional cloud pieces exist as interfaces from the start and as nothing else until
there is a service behind them ([ADR-0010](adr/0010-optional-media-relay-and-cloud-scheduler.md)):
a media relay for platforms that ingest by public URL, and a cloud scheduler for
publishing while the computer is off.

---

## What is intentionally absent

- No generation of any kind ([ADR-0011](adr/0011-no-media-generation.md)).
- No automatic transformation of a user's file — no crop, resize, upscale, transcode or
  re-encode. Validation reports; it does not repair.
- No scraping, browser automation or stored social passwords.
- No autonomous agent that decides to publish.
- No telemetry unless the user turns it on.
- No stub routes. A route exists when it works.
