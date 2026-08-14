/**
 * Hand-written aliases over the generated OpenAPI types.
 *
 * `src/generated/api.ts` is produced by `make openapi` and is not committed, so
 * this module must stay compilable without it. The `Api` namespace is therefore
 * re-exported through a type-only import that tolerates its absence at authoring
 * time; run `make openapi` before typechecking a consumer that uses it.
 *
 * Enumerations below are duplicated from the backend on purpose: they drive UI
 * layout (Kanban columns, status colours, filter order), so the frontend needs
 * them as ordered runtime values, which a generated `.d.ts` cannot provide.
 * `types.test.ts` asserts they match the OpenAPI document when it is present.
 */

/** Membership roles. Order is broadest to narrowest authority. */
export const ROLES = [
  "owner",
  "creative_lead",
  "operator",
  "reviewer",
  "compliance",
  "analyst",
  "agent",
] as const;
export type Role = (typeof ROLES)[number];

/** Who caused a change, as recorded on every audit entry. */
export const ACTOR_TYPES = ["user", "system", "agent"] as const;
export type ActorType = (typeof ACTOR_TYPES)[number];

/** Influencer lifecycle. Order matches the lifecycle, not the alphabet. */
export const INFLUENCER_STATUSES = ["draft", "active", "paused", "archived"] as const;
export type InfluencerStatus = (typeof INFLUENCER_STATUSES)[number];

/**
 * The influencer lifecycle transition table, mirroring the backend state machine.
 *
 * Used only to decide which actions to *offer*. The backend re-validates every
 * transition, so a stale copy here can never produce an illegal state change —
 * at worst it shows a button that returns 409.
 */
export const INFLUENCER_TRANSITIONS: Readonly<
  Record<InfluencerStatus, readonly InfluencerStatus[]>
> = {
  draft: ["active", "archived"],
  active: ["paused", "archived"],
  paused: ["active", "archived"],
  archived: [],
};

/** Content pillars. */
export const CONTENT_PILLARS = ["reach", "trust", "conversion"] as const;
export type ContentPillar = (typeof CONTENT_PILLARS)[number];

/** Risk levels, ascending. */
export const RISK_LEVELS = ["low", "medium", "high"] as const;
export type RiskLevel = (typeof RISK_LEVELS)[number];

// --- API shapes ------------------------------------------------------------
//
// Mirrors of the response models the implemented screens consume. These are
// hand-written rather than generated so the app compiles before `make openapi`
// has ever run; the generated document remains the contract of record.

export interface Paginated<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export interface UserRead {
  id: string;
  email: string;
  display_name: string;
  status: "invited" | "active" | "suspended" | "disabled";
  created_at: string;
  updated_at: string;
}

export interface MembershipSummary {
  organization_id: string;
  organization_name: string;
  organization_slug: string;
  role: Role;
}

export interface MeRead {
  user: UserRead;
  active_organization_id: string;
  active_role: Role;
  actor_type: ActorType;
  permissions: string[];
  memberships: MembershipSummary[];
}

export interface TokenPair {
  access_token: string;
  refresh_token: string;
  token_type: "bearer";
  expires_in_seconds: number;
  organization_id: string;
}

export interface DisclosurePolicyRead {
  id: string;
  organization_id: string;
  code: string;
  name: string;
  ai_disclosure_required: boolean;
  ai_disclosure_text: string;
  advertising_disclosure_required: boolean;
  advertising_disclosure_text: string;
  requires_high_risk_approval: boolean;
  is_default: boolean;
  notes: string | null;
  created_at: string;
  updated_at: string;
}

export interface InfluencerRead {
  id: string;
  organization_id: string;
  code: string;
  public_name: string;
  status: InfluencerStatus;
  niche: string | null;
  primary_language: string;
  primary_market: string;
  adult_representation_confirmed: boolean;
  disclosure_policy_id: string | null;
  created_at: string;
  updated_at: string;
  archived_at: string | null;
}

export interface InfluencerDetail extends InfluencerRead {
  disclosure_policy: DisclosurePolicyRead | null;
  current_version_number: number | null;
  /** Why this influencer cannot be activated yet. Empty means it can. */
  activation_blockers: string[];
}

export interface InfluencerVersionRead {
  id: string;
  influencer_id: string;
  version_number: number;
  change_summary: string;
  biography: string | null;
  tone_of_voice: string | null;
  personality_traits: string[];
  prohibited_topics: string[];
  visual_constraints: Record<string, unknown>;
  speech_constraints: Record<string, unknown>;
  created_by: string;
  created_at: string;
  is_current: boolean;
}

export interface AuditLogRead {
  id: string;
  sequence_number: number;
  organization_id: string;
  actor_type: ActorType;
  actor_id: string | null;
  action: string;
  entity_type: string;
  entity_id: string;
  before_data: Record<string, unknown> | null;
  after_data: Record<string, unknown> | null;
  request_id: string | null;
  created_at: string;
}

/** A changed field, as computed by the backend for a history tab. */
export interface FieldChange {
  from: unknown;
  to: unknown;
}

export interface AuditLogDiff {
  entry: AuditLogRead;
  changed_fields: Record<string, FieldChange>;
}

/** The single error envelope used by every non-2xx response. */
export interface ApiErrorBody {
  error: {
    code: string;
    message: string;
    details: Record<string, unknown>;
    request_id: string | null;
  };
}
