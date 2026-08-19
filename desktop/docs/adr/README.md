# Architecture decision records

One file per decision. Each states what was decided, what it costs, and what was rejected —
the rejected alternatives are usually the most useful part when revisiting a decision later.

Format: **Context** (what forced a decision), **Decision** (what was chosen, specifically),
**Consequences** (gained / given up, honestly), **Alternatives considered** (and why not).

| ADR                                                        | Decision                                                                     |
| ---------------------------------------------------------- | ---------------------------------------------------------------------------- |
| [0001](0001-desktop-local-first.md)                        | Desktop local-first: one installer, all state local, cloud optional          |
| [0002](0002-fastapi-sidecar-inside-tauri.md)               | Tauri owns the OS, a bundled FastAPI sidecar owns the domain                 |
| [0003](0003-sqlite-local-postgresql-cloud.md)              | SQLite locally, PostgreSQL kept possible for the cloud                       |
| [0004](0004-managed-local-media-library.md)                | Imports are copied into a library the application manages                    |
| [0005](0005-human-approval-before-automatic-publishing.md) | Automatic publishing, but only of an approved snapshot                       |
| [0006](0006-social-connector-boundary.md)                  | Every platform behind one `SocialConnector` and a manifest                   |
| [0007](0007-llm-provider-boundary.md)                      | LLM providers are adapters; persona assembly sits above them                 |
| [0008](0008-windows-secure-secret-storage.md)              | Secrets in Windows Credential Manager, `secret_ref` in the database          |
| [0009](0009-signed-update-channel.md)                      | Signed updates, verified before install, database backed up before migration |
| [0010](0010-optional-media-relay-and-cloud-scheduler.md)   | Media relay and cloud scheduler: interfaces now, service later               |
| [0011](0011-no-media-generation.md)                        | No media generation, and no automatic transformation of the user's file      |

ADR-0005 **supersedes** the donor's
[ADR-0003](../../../docs/adr/0003-human-approval-gate.md), which forbade automatic
publishing outright. The donor's other three rules carry over unchanged — see
[donor-reference.md](../donor-reference.md).
