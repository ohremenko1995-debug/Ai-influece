# ADR-0007 — LLM providers behind an adapter, persona assembled above it

- **Status:** accepted
- **Date:** 2026-08-19

## Context

The application writes publication text in a character's voice. That voice comes from the
Character Bible, the Voice Profile, previously approved examples and the target platform's
rules — none of which is a property of any language model.

Five provider families are in scope: OpenAI (Responses API), Anthropic (Messages API),
Google Gemini (`generateContent`), Mistral (Chat), and any OpenAI-compatible endpoint at a
configurable base URL. Their request shapes, streaming, structured output, vision support
and usage reporting all differ. Model names change every few months, and a user must be able
to switch to a newly released model without waiting for a release of this application.

The material at stake is sensitive: a character's identity document, and optionally the
user's photographs.

## Decision

**Providers are adapters. Persona construction happens above them, once, in
`PersonaPromptService`.**

### Split of responsibility

| `PersonaPromptService`                                                                                                                                                                                                                                                                   | Provider adapter                                     |
| ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------- |
| builds a provider-neutral request from the current Character Bible version, the current Voice Profile version, selected approved examples, platform rules, the user's brief, an attached script, desired language and length, an optional media description, and disclosure requirements | translates that request to one vendor's API and back |

An adapter that assembled personality itself would produce a different character per
provider, and switching providers would silently change the voice. That is the failure this
split exists to prevent.

### The interface

```python
class LLMProvider(Protocol):
    def manifest(self) -> LLMProviderManifest: ...
    async def test_connection(self, connection) -> HealthResult: ...
    async def list_models(self, connection) -> list[LLMModelInfo]: ...
    async def generate_variants(self, connection, request) -> TextGenerationResult: ...
```

The manifest declares `supports_model_listing`, `supports_structured_output`,
`supports_vision`, `supports_streaming`, `supports_usage` and `auth_mode`, so the UI can
show only what a provider can actually do.

### Model IDs are configuration

**No marketing model name appears in business logic.** The model is a setting on the
connection, validated against `list_models` where the provider supports listing and accepted
as free text where it does not. A new model is a settings change, not a release.

### One request shape, one response shape

Input carries `character_id`, the Bible and Voice Profile version ids, target platforms,
goal, brief, language, length, optional tone override, `variants_count` (1–5, default 5), an
optional script asset, an optional media asset, `include_media`, and extra instructions.

Output is a list of variants, each with text, optional title, hook, CTA, hashtags and
warnings, plus the provider, the configured model id and usage counters when available.

Pinning the Bible and Voice Profile **version** ids, not just the character, is what makes a
generation reproducible and auditable: the identity can change afterwards without rewriting
history.

### Vision is off by default

`include_media=false` unless the user turns it on for that request. The toggle appears only
when the provider and model support vision. Before the first send, an explicit notice states
what will leave the machine. The choice can be remembered per connection, and the default
for the next connection stays off. Whether an image was sent is recorded on the generation
record; the image never enters logs or telemetry.

### Feedback, not training

The user can accept, reject, edit, mark a variant as sounding like the character or not, and
save a final post as an approved example. Only explicitly selected examples enter future
prompt context. **No fine-tuning, no hidden learning, no silent accumulation of the user's
posts into a model.**

### Secrets

An API key is a `secret_ref` in the database and a value in Windows Credential Manager
([ADR-0008](0008-windows-secure-secret-storage.md)). Provider payloads are redacted in logs,
and a full provider response never reaches telemetry or the audit log — which records that a
generation happened and which variant was chosen, not the vendor's raw output.

## Consequences

**Gained**

- The character's voice is one implementation, so switching provider changes cost and quality,
  not identity.
- A new provider is one adapter and a manifest.
- Users follow model releases at their own pace.
- Generations are reproducible: the exact identity versions are recorded.
- The privacy-sensitive decision — sending an image — is one explicit flag in one place.

**Given up**

- **Provider-specific strengths are not exposed.** A vendor's bespoke tool-use or caching
  feature does not fit the neutral request. Adding it means extending the shared shape and
  considering every adapter.
- **Structured output is uneven.** Providers without it need parsing and validation, so variant
  extraction has a fallback path that is inherently less reliable.
- **Usage and cost reporting are best-effort.** Not every provider returns token counts, so the
  numbers are nullable and cannot be presented as authoritative.
- **A neutral prompt is not an optimal prompt.** A provider-tuned prompt would score better on
  that provider; consistency of voice is judged more valuable than a marginal quality gain.

## Alternatives considered

| Alternative                                   | Why not                                                                                                                                      |
| --------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------- |
| One provider only                             | Locks the user's cost and availability to one vendor, and makes a local or self-hosted model impossible.                                     |
| A third-party abstraction library             | Adds a dependency that lags provider releases, and its abstraction is not ours to fix when it breaks.                                        |
| Let each adapter build its own persona prompt | The character would sound different per provider, and the difference would be invisible until someone noticed the voice had drifted.         |
| Hardcode a default model per provider         | Guarantees a stale default and a release whenever a model is renamed or retired.                                                             |
| Vision on by default when supported           | Sends the user's photographs to a third party without a decision. The one setting most deserving of an explicit opt-in.                      |
| Fine-tune on the user's posts                 | Hidden learning over personal content, an ongoing cost, and no way to explain why the model said something. Explicit examples are auditable. |
