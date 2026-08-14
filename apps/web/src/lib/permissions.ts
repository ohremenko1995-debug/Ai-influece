import type { MeRead } from "@influenceros/types";

/**
 * Permission names, mirroring `app/shared/permissions/permissions.py`.
 *
 * Only the ones the implemented screens consult are listed; the rest arrive with
 * their features. These drive *affordances* — the backend re-checks every call, so
 * a stale entry here can hide a button but can never grant access.
 */
export const PERMISSIONS = {
  orgRead: "org:read",
  orgUpdate: "org:update",
  orgMemberManage: "org:member_manage",
  influencerRead: "influencer:read",
  influencerCreate: "influencer:create",
  influencerUpdate: "influencer:update",
  influencerArchive: "influencer:archive",
  influencerVersionCreate: "influencer:version_create",
  policyRead: "policy:read",
  policyUpdate: "policy:update",
  auditRead: "audit:read",
  dashboardRead: "dashboard:read",
} as const;

export type PermissionName = (typeof PERMISSIONS)[keyof typeof PERMISSIONS];

/** Whether the current session holds `permission`. */
export function can(me: MeRead | null, permission: PermissionName | string): boolean {
  if (!me) return false;
  return me.permissions.includes(permission);
}

/** Whether the session holds every listed permission. */
export function canAll(me: MeRead | null, permissions: readonly string[]): boolean {
  if (!me) return false;
  return permissions.every((permission) => me.permissions.includes(permission));
}
