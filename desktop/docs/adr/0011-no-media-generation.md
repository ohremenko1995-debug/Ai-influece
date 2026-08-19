# ADR-0011 — No media generation inside InfluencerOS Desktop

- **Status:** accepted
- **Date:** 2026-08-19

## Context

The donor was built around generation: a ComfyUI adapter, LoRA and workflow versioning,
recipes, generation jobs, GPU queues, QA of generated frames, identity-drift scoring, and
asset provenance recording the prompt, model and seed behind every image.

This product deliberately does not do any of that. The user creates the character's
appearance elsewhere, prepares photographs elsewhere, prepares video elsewhere, and writes
scripts elsewhere. What they lack is everything that happens **after** the file exists:
keeping a character consistent, checking a file against nine platforms' requirements,
writing text in the character's voice, getting a decision recorded, and publishing on time
to several accounts.

The pull towards adding "just a little" generation is strong and will recur. Auto-crop for
Instagram's aspect ratio. A quick transcode when a codec is unsupported. An upscale when a
file is below a platform's minimum. Each looks like a convenience.

## Decision

**No generation, and no automatic transformation of the user's file. Ever.**

Not implemented, and not to be added:

- image generation
- video generation
- LoRA training
- GPU management
- a ComfyUI or any workflow editor
- storage of prompts, models, LoRAs or image provenance
- automatic montage or enhancement
- **automatic crop, resize, upscale or transcode**

### Validation reports; it does not repair

The engine reads a file and states what is wrong with it for a given platform. Critical
findings block publication. Warnings can be acknowledged, and the acknowledgement is
audited.

It never fixes anything. A crop chooses what to cut from a photograph; a transcode chooses
what quality to lose. Those are the user's decisions, made in their own tools, where they can
see the result. An automatic transformation would mean publishing something the user never
saw — which is the same failure that
[ADR-0005](0005-human-approval-before-automatic-publishing.md) exists to prevent, arriving
through a different door.

### No provenance fields

There are deliberately no columns for prompt, model, seed, sampler, LoRA or generation
lineage.

They cannot be trustworthy. This application receives a finished file; whatever it recorded
would be typed in by hand, and a field that looks authoritative but is unverified is worse
than no field. If provenance is needed later it must come from a signed standard such as
C2PA, read from the file itself — not from a text box.

### What remains, and why it is enough

| The user does elsewhere   | The application does                                                             |
| ------------------------- | -------------------------------------------------------------------------------- |
| creates the appearance    | keeps the identity: Character Bible and Voice Profile, versioned and append-only |
| prepares photos and video | manages the library, hashes it, validates it against platform rules              |
| writes the script         | stores it as an attachment and can pass it to the LLM                            |
| decides what to publish   | records the approval, binds it to an exact snapshot, and publishes on time       |

The transparency obligations inherited from the donor stay in force: characters are openly
virtual, disclosure is part of the approved snapshot, and no feature exists to hide that
content is synthetic, to impersonate a real person, or to clone a voice without a recorded
confirmation.

## Consequences

**Gained**

- No GPU, no CUDA, no model weights, no multi-gigabyte download, no ComfyUI to install. The
  installer stays small and the application runs on an ordinary PC.
- The whole generation domain — jobs, queues, recipes, workflow versions, QA of frames —
  simply does not exist, which is a large amount of the donor's complexity avoided.
- The product has a clear answer to "what is this": the layer between finished material and a
  published post.
- The user keeps their own pipeline. They are not forced into whatever generator this
  application would have chosen.
- What is published is what the user approved, byte for byte.

**Given up**

- **The workflow spans two tools.** Generate in one place, import here. That is friction on every
  post, and it is the deliberate cost of this decision.
- **A platform rejection is a round trip.** "Wrong aspect ratio for a Reel" means going back to
  another tool, fixing it and re-importing, where a crop button would have taken one click.
- **No lineage.** Nobody can ask this application which prompt produced an image, because it
  genuinely does not know.
- **A visible competitive gap** against a product that does both. Accepted: doing the post-production
  half well is the goal, and doing both halves badly is the alternative.

## Alternatives considered

| Alternative                                      | Why not                                                                                                                                                 |
| ------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Port the donor's ComfyUI adapter                 | Requires ComfyUI, a GPU and model weights on the user's machine, contradicting [ADR-0001](0001-desktop-local-first.md). It is also not the requirement. |
| Call a hosted generation API                     | A network dependency, a per-image cost and a second class of credential, for a capability the user already has covered.                                 |
| Automatic crop and resize per platform           | Silently changes what was approved. The most tempting of these, and the most dangerous.                                                                 |
| Automatic transcode when a codec is unsupported  | Re-encoding loses quality and the user never sees the result before it is published.                                                                    |
| Manual provenance fields for the user to fill in | Unverifiable data that looks authoritative. Worse than nothing.                                                                                         |
| "Optional" generation behind a feature flag      | Optional features are still maintained, tested, documented and supported. The scope discipline is the point.                                            |
