# InfluencerOS Desktop

A Windows desktop application for managing virtual characters, ready-made photo and video
material, publication texts, connected social accounts, a calendar, and automatic
publishing.

Media production is **outside this product**. The application never generates images or
video, never trains a LoRA, never touches ComfyUI, and stores no prompts, models or image
provenance. The user prepares the material elsewhere; InfluencerOS Desktop manages it,
checks it against platform requirements, helps write the text with a persona-tuned LLM,
and publishes it — after a human has approved that exact version.

> The LLM proposes text. The application performs the technical publication. The decision
> to publish is always made by a person.

---

## Status

**Stage 0 of 10 — repository, architectural rules and ADRs.** No application code exists
yet. Nothing in this directory runs.

The single source of truth for what is built and what is not is
[IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md). Documents in `docs/` that describe
future stages carry an explicit status banner; treat any capability without a row marked
`done` in the status file as unimplemented.

| Stage | Scope                                                                          | State    |
| ----- | ------------------------------------------------------------------------------ | -------- |
| 0     | Repository, donor reference, ported architecture rules, ADR-0001…0011          | **done** |
| 1     | Tauri shell, Next static export, FastAPI sidecar, SQLite, first-run, auth      | next     |
| 2     | Characters, Character Bible versions, Voice Profile versions, disclosure       | planned  |
| 3     | Media Library, secure file grants, managed copy, ffprobe validation            | planned  |
| 4     | Publication groups and targets, presets, approval snapshots, calendar, jobs    | planned  |
| 5     | First real social connector (Telegram first), then YouTube, Meta, TikTok, …    | planned  |
| 6     | LLM framework: PersonaPromptService, fake/OpenAI/Anthropic/compatible adapters | planned  |
| 7     | Release quality: signed updates, migration backup, diagnostics bundle          | planned  |
| 8     | Cloud extension: media relay, cloud scheduler, sync, team access               | planned  |
| 9     | Insights: reach, likes, reactions — beyond the spec, **not designed**          | planned  |
| 10    | Conversations: comment and DM replies — beyond the spec, **not designed**      | planned  |

---

## Where this code lives

This project is specified as a **separate repository**, `influenceros-desktop`. It is
currently developed as a self-contained subtree of the donor repository instead, because
creating a second repository was outside the authority this working session was given.

The layout below `desktop/` is exactly the layout the standalone repository will have, and
[docs/repository-extraction.md](docs/repository-extraction.md) holds the one command that
turns it into that repository with its history intact. Nothing here imports from the donor
at runtime, and nothing in the donor imports from here.

---

## Target repository layout

Directories marked _(stage n)_ are created by that stage and do not exist yet.

```text
influenceros-desktop/
├── apps/
│   ├── desktop-ui/                 # Next.js App Router, static export      (stage 1)
│   ├── local-api/                  # FastAPI sidecar                        (stage 1)
│   │   ├── app/{api,core,modules,shared}/
│   │   ├── alembic/
│   │   └── tests/
│   └── desktop-shell/              # Tauri 2 / Rust                         (stage 1)
│       ├── src-tauri/
│       └── binaries/               # bundled sidecar + ffprobe.exe
├── packages/
│   ├── ui/                         # shared React primitives                (stage 1)
│   ├── types/                      # types generated from OpenAPI           (stage 1)
│   ├── config/                     # eslint / prettier / tsconfig bases     (stage 1)
│   └── connector-contracts/        # connector manifests + contract fixtures (stage 5)
├── tools/
│   ├── build-sidecar/              # PyInstaller-style sidecar build        (stage 1)
│   ├── release/                    # signing, latest.json, checksums        (stage 7)
│   └── fixtures/                   # media fixtures for validation tests    (stage 3)
├── docs/
│   ├── adr/                        # architecture decision records          done
│   ├── architecture.md                                                    # done
│   ├── donor-reference.md                                                 # done
│   ├── implementation-plan.md                                             # done
│   ├── repository-extraction.md                                           # done
│   ├── security.md                                                        # done
│   ├── domain-model.md                                                     (stage 2)
│   ├── api.md                                                              (stage 1)
│   ├── connector-sdk.md                                                    (stage 4)
│   └── releases.md                                                         (stage 7)
├── CLAUDE.md
├── IMPLEMENTATION_STATUS.md
├── README.md
├── pnpm-workspace.yaml                                                      (stage 1)
└── justfile                                                                 (stage 1)
```

---

## Architecture in one page

One executable, three processes, no external services.

```text
InfluencerOS.exe (Tauri 2)
├── WebView — Next.js static UI, talks only to an ApiTransport
├── Rust desktop bridge — updater, file picker, Credential Manager, tray, API proxy
└── influenceros-local-api.exe (FastAPI sidecar)
    ├── SQLite (WAL, foreign keys on)
    ├── managed media library
    ├── validation engine
    ├── publication scheduler
    ├── social connectors
    ├── LLM connectors
    └── audit log
```

The rules that shape almost every decision:

1. **No media generation, ever.** ([ADR-0011](docs/adr/0011-no-media-generation.md))
2. **Local-first.** A user installs one signed installer. No Docker, Python, Node,
   PostgreSQL or Redis on their machine. ([ADR-0001](docs/adr/0001-desktop-local-first.md))
3. **The domain lives in Python, not Rust.** Rust owns the OS: lifecycle, tray, secrets,
   updater, file grants. ([ADR-0002](docs/adr/0002-fastapi-sidecar-inside-tauri.md))
4. **Automatic publishing is allowed only for a platform version that holds a valid human
   approval.** Any change to the file, text, disclosure, account, time or platform
   settings voids that approval.
   ([ADR-0005](docs/adr/0005-human-approval-before-automatic-publishing.md))
5. **Secrets never reach SQLite, JSON, `.env`, frontend storage or logs.** The database
   holds a `secret_ref`; the secret itself lives in Windows Credential Manager.
   ([ADR-0008](docs/adr/0008-windows-secure-secret-storage.md))
6. **Every consequential change writes an audit row in the same transaction** as the
   change itself.

The full rule set a contributor must follow is [CLAUDE.md](CLAUDE.md).

---

## Documentation

| Document                                                       | Contents                                                             |
| -------------------------------------------------------------- | -------------------------------------------------------------------- |
| [CLAUDE.md](CLAUDE.md)                                         | the rules, the commands, the invariants — read before changing code  |
| [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md)           | what actually exists, per stage, with the gate results that prove it |
| [docs/architecture.md](docs/architecture.md)                   | processes, transport, layering, transactions, deployment shape       |
| [docs/donor-reference.md](docs/donor-reference.md)             | what is inherited from the web MVP, and what is deliberately not     |
| [docs/security.md](docs/security.md)                           | secrets, session model, telemetry, disclosure obligations            |
| [docs/implementation-plan.md](docs/implementation-plan.md)     | the stage plan, module by module                                     |
| [docs/repository-extraction.md](docs/repository-extraction.md) | how this subtree becomes its own repository                          |
| [docs/adr/](docs/adr/)                                         | architecture decision records 0001–0011                              |
