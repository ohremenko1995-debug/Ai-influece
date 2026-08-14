import {
  ACTOR_TYPES,
  INFLUENCER_STATUSES,
  INFLUENCER_TRANSITIONS,
  ROLES,
  type InfluencerStatus,
} from "@influenceros/types";
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

/**
 * Drift guard between the hand-written enums in `@influenceros/types` and the
 * backend's OpenAPI document.
 *
 * Those enums exist as ordered runtime values because they drive UI layout, which a
 * generated `.d.ts` cannot provide. That duplication is only safe if something
 * checks it, which is what this file does.
 *
 * `docs/api/openapi.json` is produced by `make openapi` and is not committed, so the
 * assertions are skipped when it is absent rather than failing a fresh checkout.
 */
// Resolved from the working directory, not `import.meta.url`: under the jsdom
// environment `import.meta.url` is not a file: URL. Vitest runs with cwd=apps/web.
const OPENAPI_PATH = resolve(process.cwd(), "../../docs/api/openapi.json");

interface OpenApiDocument {
  components?: { schemas?: Record<string, { enum?: string[] }> };
  paths?: Record<string, unknown>;
}

function loadDocument(): OpenApiDocument | null {
  if (!existsSync(OPENAPI_PATH)) return null;
  return JSON.parse(readFileSync(OPENAPI_PATH, "utf8")) as OpenApiDocument;
}

const document = loadDocument();
const describeContract = document ? describe : describe.skip;

describeContract("OpenAPI contract", () => {
  function enumValues(schemaName: string): string[] {
    const schema = document?.components?.schemas?.[schemaName];
    expect(schema, `schema ${schemaName} is missing from the OpenAPI document`).toBeDefined();
    expect(schema?.enum, `schema ${schemaName} has no enum`).toBeDefined();
    return schema?.enum ?? [];
  }

  it("ROLES matches the backend Role enum", () => {
    expect([...ROLES].sort()).toEqual([...enumValues("Role")].sort());
  });

  it("ACTOR_TYPES matches the backend ActorType enum", () => {
    expect([...ACTOR_TYPES].sort()).toEqual([...enumValues("ActorType")].sort());
  });

  it("INFLUENCER_STATUSES matches the backend InfluencerStatus enum", () => {
    expect([...INFLUENCER_STATUSES].sort()).toEqual([...enumValues("InfluencerStatus")].sort());
  });

  it("exposes the endpoints the implemented screens depend on", () => {
    const paths = Object.keys(document?.paths ?? {});
    for (const required of [
      "/api/v1/auth/login",
      "/api/v1/me",
      "/api/v1/influencers",
      "/api/v1/influencers/{influencer_id}",
      "/api/v1/influencers/{influencer_id}/status",
      "/api/v1/influencers/{influencer_id}/versions",
      "/api/v1/influencers/{influencer_id}/audit-logs",
      "/api/v1/disclosure-policies",
      "/api/v1/audit-logs",
    ]) {
      expect(paths, `missing endpoint ${required}`).toContain(required);
    }
  });
});

describe("influencer transition table", () => {
  it("covers every status", () => {
    expect(Object.keys(INFLUENCER_TRANSITIONS).sort()).toEqual([...INFLUENCER_STATUSES].sort());
  });

  it("treats archived as terminal, so the UI offers no way out of it", () => {
    expect(INFLUENCER_TRANSITIONS.archived).toEqual([]);
  });

  it("never lets a status transition to itself", () => {
    for (const status of INFLUENCER_STATUSES) {
      expect(INFLUENCER_TRANSITIONS[status]).not.toContain(status);
    }
  });

  it("only lists real statuses as targets", () => {
    const known = new Set<string>(INFLUENCER_STATUSES);
    for (const targets of Object.values(INFLUENCER_TRANSITIONS)) {
      for (const target of targets as readonly InfluencerStatus[]) {
        expect(known.has(target)).toBe(true);
      }
    }
  });

  it("matches the backend table exactly", () => {
    // Mirrors app/modules/influencers/state_machine.py.
    expect(INFLUENCER_TRANSITIONS).toEqual({
      draft: ["active", "archived"],
      active: ["paused", "archived"],
      paused: ["active", "archived"],
      archived: [],
    });
  });
});
