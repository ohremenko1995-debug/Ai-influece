# ADR-0004 — A managed local media library

- **Status:** accepted
- **Date:** 2026-08-19

## Context

The user prepares photos and videos elsewhere and imports them
([ADR-0011](0011-no-media-generation.md)). Those files are the product's most valuable
content: a publication references one, an approval hashes it, and an audit row must be able
to say what was published months later.

Referencing the user's own path is the tempting option and it fails immediately. People
rename folders, move work to an external drive, clear a Downloads directory, and edit a
file in place after approving it. Any of those silently changes or destroys what a
publication points at. Storing an absolute path makes the whole library break when
`DATA_ROOT` moves.

The donor solved the equivalent problem with MinIO and presigned uploads. There is no
object store here.

## Decision

**On import, the application copies the file into a library it owns, and refers to it by a
path relative to `DATA_ROOT`. The user's original is never touched.**

### Layout

```text
<DATA_ROOT>/
├── database/influenceros.db
├── media/originals/       imported files, managed
├── media/thumbnails/      generated previews
├── attachments/           scripts and other non-publishable material
├── cache/
├── exports/
├── logs/
├── backups/
└── config/app.json
```

### Import

1. The user picks files through the OS dialog; Rust returns a scoped grant for exactly
   those paths. The sidecar never browses the filesystem on its own.
2. Copy to a staging file inside the library.
3. Compute SHA-256 while copying.
4. `fsync`, then **atomic rename** into place. A crash mid-import leaves a staging file,
   never a half-written asset.
5. Record the relative path, the SHA-256, the original filename, the size and the extracted
   metadata.
6. If the hash already exists, **warn** and let the user decide. Do not silently deduplicate:
   two copies of one file may be two publications with different histories.
7. Never delete or modify the user's source file.

### Paths

The database stores paths **relative to `DATA_ROOT`**. `DATA_ROOT` itself lives in
`config/app.json` and in nothing else, so moving the folder means updating one value.

`DATA_ROOT` is never placed inside a directory the updater replaces
([ADR-0009](0009-signed-update-channel.md)) and never inside `Program Files`. In portable
mode it defaults to `./InfluencerOSData` next to the executable; in installed mode the
first-run wizard asks, checks write access and free space, and refuses a protected system
location.

### Deletion

No hard deletes by default:

| Action                      | Effect                                                                        |
| --------------------------- | ----------------------------------------------------------------------------- |
| Archive                     | the asset leaves the pickers, keeps its row, its file and its history         |
| Physical delete             | a separate, explicitly confirmed operation that removes the managed file      |
| Referenced by a publication | the file is not removable while a publication or approval record refers to it |

### Metadata and validation

Read-only inspection: Pillow for images, a bundled `ffprobe.exe` for video. The engine
reports; it never repairs. No crop, resize, upscale, transcode or re-encode — an automatic
transformation would mean publishing something the user never saw
([ADR-0011](0011-no-media-generation.md)).

Critical findings block publication. Warnings can be acknowledged, and the acknowledgement
is audited with the identity of whoever accepted it.

## Consequences

**Gained**

- A publication's media cannot vanish or change underneath it.
- The SHA-256 is what makes the approval snapshot meaningful: an edited file is a different
  file, so the approval is void ([ADR-0005](0005-human-approval-before-automatic-publishing.md)).
- Backup and moving the library are directory operations.
- Atomic rename means a crash or a power cut cannot produce a corrupt asset.

**Given up**

- **Disk usage doubles** for every import. Stated in the wizard; a media library of finished
  renders is the user's own material, and the alternative is broken references.
- **Import is as slow as a file copy** plus a hash. Large videos take visible seconds, so the
  UI must show progress rather than appear frozen.
- **Two places can disagree.** A file deleted from the library folder by hand leaves a row
  pointing at nothing. A consistency check that reports missing files is needed, and belongs
  with the media stage.
- **Edits outside the app are invisible until re-imported.** That is the intended trade: the
  library is a snapshot, not a live link.

## Alternatives considered

| Alternative                        | Why not                                                                                                                                            |
| ---------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| Reference the user's original path | Breaks on rename, move, delete or edit. Silently changes what a publication points at, after approval.                                             |
| Hardlink instead of copy           | Same-volume only, and an in-place edit through either name changes the "copy" — which defeats the purpose.                                         |
| Store media as BLOBs in SQLite     | Multi-gigabyte databases, slow backups, no streaming to a connector, and thumbnails become a second copy anyway.                                   |
| Absolute paths in the database     | `DATA_ROOT` becomes unmovable, and every row has to be rewritten if the user relocates their library.                                              |
| Silent deduplication by hash       | Two publications may legitimately use the same bytes with different histories. Merging them loses information the audit trail is supposed to keep. |
| Hard delete on request             | Destroys the evidence for a publication that already happened. Archive first, physical deletion as a separate confirmed step.                      |
