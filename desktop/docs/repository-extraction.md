# Turning `desktop/` into the `influenceros-desktop` repository

## Why this is a subtree right now

The specification calls for a new repository. The working session that produced stage 0 was
authorised for exactly one repository — the donor — and creating a second one under the
account was outside that authority, so the project was scaffolded as a subtree instead.

This is a hosting decision, not an architectural one. The tree below `desktop/` is laid out
exactly as the standalone repository will be. Nothing here imports the donor at runtime,
nothing in the donor imports this, and no build step crosses the boundary. Extraction is
mechanical.

## Extraction

`git subtree split` rewrites the commits that touched `desktop/` into a branch whose root
is `desktop/`, keeping authorship and dates:

```bash
# In the donor working copy
git subtree split --prefix=desktop -b influenceros-desktop-main

# Create the new empty repository on the host first, then
git init --bare ../influenceros-desktop.git
git push ../influenceros-desktop.git influenceros-desktop-main:main
# or straight to the remote
git push git@github.com:<owner>/influenceros-desktop.git influenceros-desktop-main:main
```

After the push, the new repository's root contains `apps/`, `packages/`, `docs/`,
`CLAUDE.md`, `README.md` and the rest — no `desktop/` prefix.

`git filter-repo --subdirectory-filter desktop` produces the same result and is faster on
large histories, but needs a separate install. `subtree split` ships with git.

## Afterwards

1. Delete `desktop/` from the donor in a single commit that references the new repository.
2. Add a line to the donor's README pointing at it.
3. Move the CI workflows: the desktop gates (§12 of [CLAUDE.md](../CLAUDE.md)) belong to the
   new repository, and the Windows release pipeline can only run there.
4. Nothing in `docs/adr/` changes. The ADRs were written for the standalone project.

## What must stay true until then

- No relative import, path alias, tsconfig reference, Python import or workspace entry
  crosses out of `desktop/`.
- The donor's root `package.json` and `pnpm-workspace.yaml` do not list anything under
  `desktop/`; the desktop project brings its own workspace file from stage 1.
- Formatting is the one shared concern: the donor's Prettier configuration currently
  formats markdown repository-wide, so files here follow it until extraction.
