# CLAUDE.md — InfluencerOS Desktop

Rules for anyone, human or model, changing code in this project. They are not style
preferences. Each one exists because breaking it produces a specific failure: a published
post nobody approved, a leaked API key, an endpoint the UI calls that returns a lie.

Read [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md) first. It says what exists. This
file says what is allowed.

---

## 1. Product boundary

**The application does not produce media.** No image generation, no video generation, no
LoRA training, no GPU management, no ComfyUI, no prompt/model/LoRA storage, no image
provenance fields, no automatic crop, resize, upscale, transcode, montage or enhancement.
It manages material the user prepared elsewhere. ([ADR-0011](docs/adr/0011-no-media-generation.md))

If a request seems to need one of those, the answer is a validation error telling the user
what to fix in their own tool — not a transformation.

**The characters are openly virtual.** Disclosure fields and checks exist to make the
synthetic nature of the content visible. Never add a feature whose purpose is to hide that
a character is synthetic, to impersonate a real person, or to clone a voice without a
recorded confirmation.

---

## 2. Layering

```text
router → service → repository → models
```

- **Domain rules live in the service layer.** Not in the router, not in the frontend, not
  in a connector.
- **Services never commit.** One unit of work per request, owned by the session
  dependency. A service that commits cannot be composed.
- **Repositories are tenant-scoped.** Every query filters on `organization_id`, including
  in local single-user mode. A cross-tenant read returns 404, never 403.
- **The domain never imports a vendor SDK.** Every external API is reached through an
  adapter that speaks the project's own types. An upstream API change must be fixable
  inside one connector file.
- **Frontend depends on `ApiTransport`, never on a URL.** No component calls `fetch`
  against a localhost port.

---

## 3. Authorization

- Permission checks happen **twice**: as a route dependency and inside the service. The
  route check is a fast guard and OpenAPI documentation; the service check is the boundary
  that also protects the scheduler, the CLI and tests.
- Check **permissions, never roles**, at the endpoint.
- The `agent` role may draft LLM text. It may never connect a social account, acknowledge
  a warning, approve a publication, change platform settings after approval, schedule,
  publish, or enable the media relay. This is enforced by a subtraction from the matrix,
  independent of what the matrix grants.

---

## 4. Versioning, approval and audit

- **Version entities are append-only.** Editing a Character Bible or a Voice Profile
  creates a new version and demotes the previous `is_current`. No repository method
  updates a version row.
- **Nothing is hard-deleted.** Archive first; physical deletion is a separate, explicitly
  confirmed operation.
- **Every publication requires a valid `ApprovalDecision`** for that specific platform
  target.
- **Changing an approved snapshot voids the approval.** The snapshot hash is recomputed
  immediately before publishing; a mismatch blocks the publish and returns the target to
  an editable state. It does not "warn and continue".
- **A domain change and its audit row are written in one transaction.** If the audit write
  fails, the change fails.
- Audit rows never contain secrets, access tokens, refresh tokens, API keys, or a full
  external provider response.

---

## 5. Publishing

- **Every publish call is idempotent**, keyed so that a retry cannot create a second post.
- Only official platform APIs. **No scraping, no browser automation, no stored social
  passwords.** The application never asks for a social network password.
- OAuth opens in the system browser, never in an embedded WebView. `state` is single-use
  with a TTL; PKCE where the platform supports it.
- A connector that cannot yet be completed for external reasons (vendor app review)
  ships as an interface plus fake/sandbox tests behind a feature flag, marked
  `requires_review`. It is never presented as ready.
- Retries: backoff with jitter for network, 5xx and rate limits; **no** automatic retry for
  invalid media or invalid settings; one refresh attempt for an expired token, then a user
  action.

---

## 6. Secrets

- API keys and OAuth tokens are **never** stored in SQLite, JSON, `.env`, frontend storage
  or logs. The database holds only a `secret_ref`.
- Secrets live in Windows Credential Manager, bound to the current Windows user.
- `secure_secret_get_for_backend` must not return a secret to JavaScript. Rust hands it to
  the sidecar over the trusted channel.
- Logs redact `Authorization` headers, cookies, tokens and provider payloads.
- Disconnect calls the platform's revoke first, then deletes the local secret. If revoke
  fails, warn — and still allow local deletion after an explicit confirmation.
- **No secrets in `.env.example`, logs, fixtures, snapshots or OpenAPI examples.** Not even
  plausible-looking ones.

Details: [docs/security.md](docs/security.md), [ADR-0008](docs/adr/0008-windows-secure-secret-storage.md).

---

## 7. Privacy

- Media is sent to an LLM only when `include_media=true` **and** the user has consented,
  with an explicit notice before the first send. The default stays off per connection.
- Telemetry and crash upload are off by default. A report may never contain post text,
  Character Bible content, media, handles without separate confirmation, API keys or a full
  provider response. The user sees a preview of the report before it is sent.
- The media relay is off by default, sends only the one selected final file, with a
  bounded TTL and an unpredictable URL.

---

## 8. Honesty about what works

- **Never register a route, connector or UI action that does not work.** The generated
  OpenAPI document is a contract; an endpoint in it is a promise.
- **Never return a placeholder success response.** If the work is not implemented, the
  endpoint does not exist.
- A capability is "done" only when a gate proves it. Record the exact gate output in
  `IMPLEMENTATION_STATUS.md` — not a summary of it.
- Documentation describes the application that exists. Anything describing a future stage
  says so in a banner at the top.

---

## 9. Data, storage and time

- SQLite with WAL and `foreign_keys=ON`. Every schema change ships an Alembic migration
  **and** a test that applies and reverses it.
- The domain must stay portable to a PostgreSQL cloud backend: no SQLite-only SQL in
  services, no reliance on SQLite type coercion.
- **PostgreSQL, Redis and Docker are never a runtime requirement for a desktop user.**
- Store paths in the database **relative to `DATA_ROOT`**. An absolute path is never the
  only source of truth.
- Import through a staging file plus atomic rename, compute SHA-256, keep the original
  filename, warn on duplicates, and never delete the user's source file.
- Never store the database or media inside a directory the updater replaces.
- **UTC in the database; the user's system timezone for display.** Always.

---

## 10. Extensibility

- Any new platform-specific setting goes through a **connector manifest and its JSON
  Schema** — never a hardcoded field or an `if platform == …` branch in the domain.
- LLM model IDs are configuration, never constants in business logic.
- All UI strings go through i18n keys. Russian ships in v1; English exists as scaffold.
  Platform and provider names are not translated.

---

## 11. Working method

1. Before each stage: a short implementation plan and the list of modules it touches.
2. After each stage: update [docs/implementation-plan.md](docs/implementation-plan.md) and
   [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md), then run every gate and record the
   exact results.
3. Small, logically grouped commits. Never one commit for a stage.
4. Every architectural decision becomes an ADR in `docs/adr/`.

---

## 12. Quality gates

Every change must leave all of these green. Commands become real as the stages that
introduce their subject land; a gate for code that does not exist yet is listed here so
nobody has to rediscover it.

```bash
# Python — apps/local-api                                    (from stage 1)
ruff check .
ruff format --check .
mypy --strict .
pytest
pytest -m migrations              # apply + reverse every Alembic revision

# TypeScript — apps/desktop-ui, packages/*                    (from stage 1)
pnpm eslint .
pnpm prettier --check .
pnpm tsc --noEmit
pnpm vitest run
pnpm --filter desktop-ui build    # static export must succeed
just openapi && git diff --exit-code   # generated types must be committed and current

# Rust — apps/desktop-shell                                   (from stage 1)
cargo fmt --check
cargo clippy -- -D warnings
cargo test

# Integration                                                 (from stage 1/4)
just test-sidecar-startup         # handshake, port selection, readiness
just test-api-smoke
just test-fake-connector-e2e      # full publication flow, no external platform
```

Release tags additionally require: a clean Windows runner, a built sidecar, bundled
`ffprobe.exe`, a Tauri NSIS build, signed updater artifacts, a generated `latest.json`, an
install smoke test, a first-launch smoke test, and an upgrade-from-previous-stable smoke
test. The GitHub Release is published only after all of them pass. The private signing key
lives only in CI secrets and never in the repository.

---

## 13. Migration order

Schema changes are applied in exactly this order, because the desktop user's database is
the only copy of their work:

1. Write the model change.
2. Generate the Alembic revision; **read it** — autogenerate against SQLite misses
   constraint and type changes.
3. Add the rollback path in the same revision (`downgrade` is not optional).
4. Add or extend the migration test that upgrades to head, downgrades to base and upgrades
   again.
5. On application start: back up the database file **before** running migrations.
6. On migration failure: do not continue on a partially changed schema. Restore the backup
   and start the previous version or a recovery mode.

Migration files are named sequentially (`0001_…`, `0002_…`), not by hash.
