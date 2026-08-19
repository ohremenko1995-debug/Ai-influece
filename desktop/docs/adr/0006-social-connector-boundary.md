# ADR-0006 — One boundary for every social platform

- **Status:** accepted
- **Date:** 2026-08-19

## Context

Nine platforms are in scope: Instagram, Facebook, Threads, TikTok, YouTube, Telegram,
Pinterest, X, VK. They disagree about everything that matters.

Authorization is OAuth2 with PKCE, OAuth2 with a callback, a bot token, or an API key.
Upload is a direct binary POST, a resumable session, or a fetch from a public URL that the
platform pulls. Some publish immediately, some return a processing id to poll, some support
native scheduling. Every one has its own aspect-ratio, duration, bitrate and caption-length
rules, and its own idea of what a "destination" is — a channel, a page, a board, a business
account. Several require vendor app review before an application may publish at all.

They also change without warning, and the product must survive that without a release.

## Decision

**The publication domain never learns a platform's name. It calls `SocialConnector`, and
everything platform-specific arrives through a manifest.**

### The interface

```python
class SocialConnector(Protocol):
    def manifest(self) -> ConnectorManifest: ...
    async def begin_connection(self, context) -> ConnectionStart: ...
    async def complete_connection(self, context, callback) -> ConnectedAccount: ...
    async def refresh_credentials(self, account) -> CredentialRefreshResult: ...
    async def test_connection(self, account) -> HealthResult: ...
    async def list_destinations(self, account) -> list[Destination]: ...
    async def validate_publication(self, account, publication) -> ConnectorValidationResult: ...
    async def publish(self, account, publication, idempotency_key: str) -> PublishResult: ...
    async def get_publish_status(self, account, external_job_id: str) -> PublishStatus: ...
    async def revoke(self, account) -> None: ...
```

`validate_publication` is separate from `publish` on purpose: the user must be able to see
a platform's objection while editing, not after a failed attempt.

### The manifest carries the differences

```python
class ConnectorManifest(BaseModel):
    key: str
    display_name: str
    version: str
    auth_mode: Literal["oauth2_pkce", "oauth2_callback", "bot_token", "api_key", "custom"]
    capabilities: ConnectorCapabilities
    publication_settings_schema: dict     # JSON Schema
    account_settings_schema: dict         # JSON Schema
    ruleset_version: str
    availability: Literal["ready", "beta", "requires_review", "disabled"]
```

Capabilities are declared, not guessed: text, image, carousel, vertical video, horizontal
video, story, short video, native scheduled publish, direct binary upload, public URL
ingestion, status polling, delete, thumbnail/cover, per-platform metadata.

**Platform-specific settings are JSON Schema, and the UI renders the form from it.** No
`if platform == "tiktok"` in the domain and no hand-written form per platform. A new setting
is a manifest change.

### Standard error vocabulary

Every connector translates its platform's failures into one set of codes:

```text
connector_auth_required        connector_token_expired
connector_permission_missing   connector_app_review_required
connector_rate_limited         connector_invalid_media
connector_invalid_settings     connector_media_relay_required
connector_external_processing  connector_duplicate_request
connector_platform_unavailable connector_unknown_error
```

Each carries a stable internal code, a safe user-facing message, whether it is retryable, a
retry-after, an external request id when that is safe to keep, and redacted details. The
retry policy in [ADR-0005](0005-human-approval-before-automatic-publishing.md) is written
against these codes, not against HTTP statuses.

### Authorization rules

- OAuth opens in the **system browser**, never an embedded WebView. An embedded browser asks
  the user to type a platform password into our window, which is exactly the habit that
  makes phishing work — and several platforms forbid it.
- `state` is single-use with a TTL; PKCE wherever supported.
- Callback via local loopback, deep link, or a future Auth Relay.
- Telegram connects with a bot token and a channel/chat selection.
- **The application never asks for a social network password.** No scraping, no browser
  automation, no stored credentials. Official APIs only.

### Honesty about readiness

A platform whose app review has not completed ships as an interface plus contract tests
against a fake or sandbox, behind a feature flag, with `availability="requires_review"`. It
is not offered as working. Order of implementation: Telegram, YouTube, the Meta group
(Instagram, Facebook, Threads), TikTok, Pinterest, X, VK — Telegram first because a bot
token needs no review, so the whole publication path can be proven end-to-end against a
real platform early.

`FakeSocialConnector` implements the full protocol and is what the end-to-end release gate
runs against.

## Consequences

**Gained**

- Adding a platform touches one package and a manifest.
- An upstream API change is localised to one adapter.
- The scheduler's retry logic is written once, against the error vocabulary.
- The UI needs no per-platform code, because the settings form is generated.
- Contract tests can be run against every connector uniformly, including the fake.

**Given up**

- **The lowest common denominator is visible.** A platform feature that fits no capability flag
  either gets a new flag — and every connector must then be considered — or it waits.
- **Manifests can lie.** A capability declared but not implemented is a runtime failure the type
  system cannot catch, so contract tests per connector are mandatory rather than nice.
- **JSON Schema-driven forms are less pretty** than hand-built ones, and complex conditional
  settings are awkward to express.
- **Ten error codes cannot express every platform's diagnostics.** Some detail is lost in
  translation; `redacted details` exists to carry what is safe to keep.

## Alternatives considered

| Alternative                                      | Why not                                                                                                                                     |
| ------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------- |
| Per-platform service classes, no shared protocol | The scheduler would need a branch per platform for retries, validation and status polling. Nine copies of the hardest logic in the product. |
| Vendor SDKs called directly from services        | Ties the domain to a vendor's types and release cadence, and makes a breaking change a cross-cutting edit.                                  |
| Hardcoded settings fields per platform           | Every new platform option becomes a migration, a schema change, a form change and a release.                                                |
| Browser automation for platforms without an API  | Explicitly forbidden. It breaks constantly, violates terms of service, and requires holding the user's password.                            |
| Ship `requires_review` connectors as ready       | Presents something that cannot work as if it can. Prohibited by the project's rules on not registering things that do not work.             |
| One generic "webhook" connector                  | Pushes the entire problem onto the user, who then has to know each platform's API.                                                          |
