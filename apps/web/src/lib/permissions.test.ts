import type { MeRead, Role } from "@influenceros/types";
import { describe, expect, it } from "vitest";

import { PERMISSIONS, can, canAll } from "./permissions";

function session(role: Role, permissions: string[]): MeRead {
  return {
    user: {
      id: "u1",
      email: "user@example.com",
      display_name: "User",
      status: "active",
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
    },
    active_organization_id: "o1",
    active_role: role,
    actor_type: role === "agent" ? "agent" : "user",
    permissions,
    memberships: [],
  };
}

describe("can", () => {
  it("is false without a session, so a logged-out UI offers nothing", () => {
    expect(can(null, PERMISSIONS.influencerCreate)).toBe(false);
    expect(canAll(null, [PERMISSIONS.influencerRead])).toBe(false);
  });

  it("reflects the permissions the server reported", () => {
    const me = session("operator", ["influencer:read", "content:create"]);
    expect(can(me, PERMISSIONS.influencerRead)).toBe(true);
    expect(can(me, PERMISSIONS.influencerCreate)).toBe(false);
  });

  it("requires every permission for canAll", () => {
    const me = session("reviewer", ["influencer:read", "qa:create"]);
    expect(canAll(me, ["influencer:read"])).toBe(true);
    expect(canAll(me, ["influencer:read", "approval:decide"])).toBe(false);
  });

  it("hides identity and policy actions from an agent session", () => {
    // Mirrors what the backend returns for the agent role: reads plus content
    // drafting and job creation, nothing else.
    const me = session("agent", [
      "influencer:read",
      "content:create",
      "content:script_create",
      "job:create",
    ]);
    expect(can(me, PERMISSIONS.influencerCreate)).toBe(false);
    expect(can(me, PERMISSIONS.influencerVersionCreate)).toBe(false);
    expect(can(me, PERMISSIONS.policyUpdate)).toBe(false);
    expect(can(me, "calendar:schedule")).toBe(false);
    expect(can(me, "approval:decide")).toBe(false);
  });
});
