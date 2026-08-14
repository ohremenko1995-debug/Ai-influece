# syntax=docker/dockerfile:1.7
# ---------------------------------------------------------------------------
# InfluencerOS web image (development target).
#
# Build context is the repository root so the pnpm workspace — apps/web plus
# packages/* — installs as one unit.
#
# This target runs `next dev`. A production image would add a `next build`
# stage and run `next start`; out of scope while the app is internal-only.
# ---------------------------------------------------------------------------
FROM node:22-slim

ENV PNPM_HOME=/usr/local/pnpm \
    PATH="/usr/local/pnpm:$PATH" \
    NEXT_TELEMETRY_DISABLED=1

RUN corepack enable && corepack prepare pnpm@10.33.0 --activate

WORKDIR /app

# Dependency layer: only the manifests, so source edits keep the install cached.
COPY package.json pnpm-lock.yaml* pnpm-workspace.yaml ./
COPY apps/web/package.json ./apps/web/
COPY packages/ui/package.json ./packages/ui/
COPY packages/types/package.json ./packages/types/
COPY packages/config/package.json ./packages/config/

RUN pnpm install --frozen-lockfile || pnpm install

COPY . .

EXPOSE 3000

CMD ["pnpm", "--filter", "@influenceros/web", "dev"]
