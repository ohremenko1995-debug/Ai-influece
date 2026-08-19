# ADR-0010 — Media relay and cloud scheduler: interfaces now, service later

- **Status:** accepted
- **Date:** 2026-08-19

## Context

Two product requirements cannot be satisfied by a purely local application, and both were
raised explicitly.

**Some platforms ingest by public URL.** They do not accept a binary upload; they fetch the
file from a URL you provide. A local application has no public URL, so for those platforms
publishing requires the file to be reachable from the internet for a short time.

**Publishing while the computer is off** is impossible locally by definition. The late-publish
recovery in [ADR-0005](0005-human-approval-before-automatic-publishing.md) softens it — a
missed slot goes out on the next start, labelled late — but a user who wants a post at 07:00
while their PC sleeps needs something else to hold it.

Both are also the most privacy-sensitive features in the product. The first uploads the
user's media to a third party. The second uploads an approved snapshot — text, disclosure,
account, media — to a service.

## Decision

**Both are connectors behind Protocols, both off by default, and neither is registered as
working until a service exists behind it.**

### MediaRelayConnector

```python
class MediaRelayConnector(Protocol):
    async def upload_temporary(self, file: LocalMedia, ttl_seconds: int, purpose: str) -> TemporaryMediaHandle: ...
    async def revoke(self, handle: TemporaryMediaHandle) -> None: ...
    async def health(self) -> HealthResult: ...
```

Constraints, all of them load-bearing:

- **Off by default.** The user enables it deliberately.
- **The UI names the exact file** that will leave the machine, before it leaves.
- **Only the one selected final file** is uploaded. Never a source, never an attachment, never
  anything else in the library.
- **Bounded TTL**, and the file is deleted after publication or expiry, whichever is first.
- **Unpredictable URL**, so it is not discoverable by guessing.
- It is used **only** for platforms that declare `public URL ingestion` and cannot accept a
  direct upload — never as a convenience for a platform that can.

A connector returning `connector_media_relay_required`
([ADR-0006](0006-social-connector-boundary.md)) is what surfaces the need, so the user is
asked in context, for a specific post, rather than agreeing to a general permission.

### CloudSchedulerConnector

```python
class CloudSchedulerConnector(Protocol):
    async def enqueue(self, approved_snapshot: CloudPublicationSnapshot) -> CloudJobHandle: ...
    async def cancel(self, handle: CloudJobHandle) -> None: ...
    async def get_status(self, handle: CloudJobHandle) -> CloudJobStatus: ...
    async def sync_results(self) -> list[CloudJobResult]: ...
```

What ships in the first version is the interface, the models and a fake implementation used
by tests. **No real cloud endpoint is registered as functional until the service exists.**

The snapshot is what makes this safe to design now: the cloud scheduler executes a decision a
person already made about one exact artefact, and it cannot make one. It receives an approved
snapshot; it has no authority to approve, and no path to modify what it was given.

### Why build the interfaces now

Two reasons, and only these.

The publication domain has to know that "publish" may be delegated. Discovering that later
means changing the scheduler, the status model, the job table and the UI at once. Declaring
the seam costs two Protocols and a fake.

And the fake implementation makes the local end-to-end test complete: the release gate can
exercise the relay-required branch without any external service.

## Consequences

**Gained**

- Platforms that ingest by URL become reachable without redesigning publication.
- The cloud scheduler is a later addition rather than a rewrite.
- The privacy decision is explicit, per file, in context — not a checkbox agreed to once.
- The fake implementations make the branches testable now.

**Given up**

- **Unused abstraction in the shipped product.** Two Protocols and a fake that no user exercises
  until the services exist. Justified only by the cost of retrofitting them, and worth
  re-examining if the cloud direction is abandoned.
- **A design that could drift from reality.** An interface written before its service can turn
  out to be the wrong shape. Mitigated by keeping both minimal.
- **The relay is a genuine privacy cost when used.** A user's photograph on a third-party host,
  briefly. Bounded and disclosed, but real, and it must not be presented as free.
- **The cloud scheduler will need the credentials to publish.** Whether that means an Auth Relay
  or delegated tokens is deliberately unresolved here; it is the hardest question in the cloud
  stage and it deserves its own ADR rather than a guess in this one.
- **Two more things a user can misconfigure**, each needing a clear off state and an honest
  health check.

## Alternatives considered

| Alternative                                         | Why not                                                                                                                      |
| --------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------- |
| Skip URL-ingestion platforms entirely               | Excludes platforms the product is meant to support, for an architectural convenience.                                        |
| Relay on by default                                 | Uploads the user's media to a third party without a decision. The single most privacy-sensitive default available.           |
| Upload everything and publish from the cloud always | Turns a local-first product into a SaaS with extra steps, and contradicts [ADR-0001](0001-desktop-local-first.md).           |
| Ask the user to host files themselves               | Pushes an infrastructure problem onto the person who asked for a desktop application.                                        |
| Wait for the service, add the interfaces later      | The retrofit touches the scheduler, the status model, the job table and the UI simultaneously. Two Protocols now is cheaper. |
| Register the cloud endpoints now as "coming soon"   | A route that does not work. Prohibited: the OpenAPI document is a contract, not a roadmap.                                   |
| Let the cloud scheduler re-approve stale snapshots  | Would make a remote service the approver. It executes decisions; it never makes them.                                        |
