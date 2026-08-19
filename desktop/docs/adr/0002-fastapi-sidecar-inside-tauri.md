# ADR-0002 — A FastAPI sidecar supervised by Tauri

- **Status:** accepted
- **Date:** 2026-08-19

## Context

[ADR-0001](0001-desktop-local-first.md) commits to a desktop application with no
prerequisites. That leaves the question of where the domain runs.

The donor's domain is Python: SQLAlchemy models, services with permission checks, an audit
service, a state machine, ~200 tests. It is the most valuable thing being inherited. The
desktop shell, meanwhile, needs things Python is bad at on Windows: a tray icon, a signed
updater, native file dialogs, DPAPI-backed credential storage, single-instance locking, OS
notifications.

The obvious risk with a local HTTP backend is that it is a local HTTP backend. A port on
`127.0.0.1` is reachable by every process on the machine and, depending on browser and
headers, by a web page the user has open.

## Decision

**Tauri 2 owns the process and the operating system. A bundled FastAPI executable owns the
domain. The UI talks to neither directly — it calls one Tauri command.**

### Division of responsibility

| Rust (Tauri)                                                                                                                         | Python (sidecar)                                                                       |
| ------------------------------------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------- |
| lifecycle, single-instance lock, tray, notifications, updater, file picker and file grants, secret storage, the proxy to the sidecar | entities, versions, validation, approval, scheduling, connectors, LLM providers, audit |

**No domain logic in Rust.** Not "as little as possible" — none. The moment a rule exists in
two languages, one of them is wrong and nobody knows which.

### The startup handshake

```text
1.  Tauri generates a random session secret, in memory.
2.  Tauri starts the sidecar bound to 127.0.0.1 on an OS-assigned free port.
3.  The secret reaches the sidecar via the process environment or an inherited IPC
    channel. It is never written to disk.
4.  The sidecar emits a readiness handshake naming the port it bound.
5.  The UI calls the Tauri command `api_request`.
6.  Rust attaches `X-Desktop-Session` and forwards the request.
7.  The sidecar requires a valid desktop session *and* a user auth session on every
    protected route.
```

The port is not fixed, so nothing can be hardcoded against it. The secret is not on disk,
so it does not survive the process. The two session checks answer different questions: the
desktop session proves the request came from our shell, the user session proves who is
asking.

The frontend depends on the `ApiTransport` interface, so the same screens work over a real
HTTPS backend later without touching a component.

### Failure handling

The sidecar is supervised. If it exits unexpectedly, the shell shows a real error state —
not a spinner — and offers a restart and access to the log. If it never becomes ready, the
UI says so rather than retrying invisibly. A window that looks like it is loading, forever,
is the worst available outcome.

## Consequences

**Gained**

- The donor's domain, its tests and its patterns transfer directly.
- Python keeps the ecosystem this product needs: Pillow, HTTP clients for every platform
  API, SQLAlchemy, Alembic.
- OpenAPI stays real, so the generated TypeScript types and the drift guard keep working.
- The same sidecar code can be served over HTTPS in the cloud version.
- Rust does what Rust is for. No Python service wrapper, no pywin32 tray, no home-grown
  updater.

**Given up**

- **Three toolchains in one release.** Python, Node and Rust all have to build and be
  gated. CI is more complex than a single-language project's.
- **Installer size.** A bundled interpreter and its dependencies cost tens of megabytes.
- **Process orchestration is our problem.** Startup latency, crash recovery, zombie
  processes after a hard kill, and a clean shutdown that does not abandon an in-flight
  publish all have to be handled explicitly.
- **An HTTP hop for local calls.** Serialisation over loopback for work that could have been
  an in-process call. Irrelevant at this scale, and it is what buys transport portability.
- **The local port exists.** Mitigated by the ephemeral port, the session secret and the
  double check — but a process running as the same Windows user can read another's
  environment, and that limit is stated plainly in [security.md](../security.md) rather
  than papered over.

## Alternatives considered

| Alternative                                    | Why not                                                                                                                                                    |
| ---------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Rewrite the domain in Rust, no sidecar         | Discards the asset being reused. Months of work for a user-invisible change, and Pillow/ffprobe/platform SDK equivalents would all need finding.           |
| PyWebView or a Python-native desktop framework | Python's Windows integration story — tray, signed updater, DPAPI — is the weak part, and that is precisely the part this would keep.                       |
| Electron with a Node backend                   | Same rewrite cost, plus a heavier runtime.                                                                                                                 |
| Embed CPython in the Rust process              | No process boundary, so a domain crash takes the window with it; and packaging an embedded interpreter with native extension wheels is harder, not easier. |
| Fixed port for the sidecar                     | Collides with whatever else the user runs, and turns a known port into an attack surface any local process can find.                                       |
| No desktop-session check, rely on `127.0.0.1`  | Loopback is not an authorization boundary. Any local process, and in some configurations a web page, can reach it.                                         |
