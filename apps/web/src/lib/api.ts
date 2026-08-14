"use client";

import type {
  AuditLogDiff,
  DisclosurePolicyRead,
  InfluencerDetail,
  InfluencerRead,
  InfluencerStatus,
  InfluencerVersionRead,
  MeRead,
  Paginated,
  TokenPair,
} from "@influenceros/types";

import { request, type RequestOptions } from "./api-client";
import { readSession } from "./auth-store";

/**
 * Typed API surface.
 *
 * One function per endpoint, each reading the session itself, so no caller has to
 * remember to attach a token or the organization header.
 */

function authed(extra: RequestOptions = {}): RequestOptions {
  const { accessToken, organizationId } = readSession();
  return { accessToken, organizationId, ...extra };
}

// --- Auth --------------------------------------------------------------------

export const authApi = {
  login: (email: string, password: string) =>
    request<TokenPair>("/api/v1/auth/login", {
      method: "POST",
      body: { email, password },
    }),

  /** Development-only. The route does not exist outside a development API. */
  devLogin: (email: string, organizationId?: string) =>
    request<TokenPair>("/api/v1/auth/dev-login", {
      method: "POST",
      body: { email, organization_id: organizationId ?? null },
    }),

  refresh: (refreshToken: string) =>
    request<TokenPair>("/api/v1/auth/refresh", {
      method: "POST",
      body: { refresh_token: refreshToken },
    }),
};

// --- Session -----------------------------------------------------------------

export const meApi = {
  read: () => request<MeRead>("/api/v1/me", authed()),
};

// --- Influencers -------------------------------------------------------------

export interface InfluencerListParams {
  status?: InfluencerStatus[];
  search?: string;
  includeArchived?: boolean;
  limit?: number;
  offset?: number;
}

export interface InfluencerCreateInput {
  code: string;
  public_name: string;
  primary_language: string;
  primary_market: string;
  niche?: string | null;
  disclosure_policy_id?: string | null;
  adult_representation_confirmed: boolean;
}

export interface InfluencerUpdateInput {
  public_name?: string;
  niche?: string | null;
  primary_language?: string;
  primary_market?: string;
  disclosure_policy_id?: string | null;
  adult_representation_confirmed?: boolean;
}

export interface CharacterBibleInput {
  change_summary: string;
  biography?: string | null;
  tone_of_voice?: string | null;
  personality_traits: string[];
  prohibited_topics: string[];
  visual_constraints: Record<string, unknown>;
  speech_constraints: Record<string, unknown>;
}

export const influencersApi = {
  list: (params: InfluencerListParams = {}) =>
    request<Paginated<InfluencerRead>>(
      "/api/v1/influencers",
      authed({
        query: {
          status: params.status,
          search: params.search,
          include_archived: params.includeArchived,
          limit: params.limit ?? 50,
          offset: params.offset ?? 0,
        },
      }),
    ),

  read: (id: string) => request<InfluencerDetail>(`/api/v1/influencers/${id}`, authed()),

  create: (input: InfluencerCreateInput) =>
    request<InfluencerDetail>("/api/v1/influencers", authed({ method: "POST", body: input })),

  update: (id: string, input: InfluencerUpdateInput) =>
    request<InfluencerDetail>(
      `/api/v1/influencers/${id}`,
      authed({ method: "PATCH", body: input }),
    ),

  changeStatus: (id: string, status: InfluencerStatus, reason?: string) =>
    request<InfluencerDetail>(
      `/api/v1/influencers/${id}/status`,
      authed({ method: "POST", body: { status, reason: reason ?? null } }),
    ),

  listVersions: (id: string, limit = 50, offset = 0) =>
    request<Paginated<InfluencerVersionRead>>(
      `/api/v1/influencers/${id}/versions`,
      authed({ query: { limit, offset } }),
    ),

  createVersion: (id: string, input: CharacterBibleInput) =>
    request<InfluencerVersionRead>(
      `/api/v1/influencers/${id}/versions`,
      authed({ method: "POST", body: input }),
    ),

  history: (id: string, limit = 50, offset = 0) =>
    request<Paginated<AuditLogDiff>>(
      `/api/v1/influencers/${id}/audit-logs`,
      authed({ query: { limit, offset } }),
    ),
};

// --- Disclosure policies -----------------------------------------------------

export const policiesApi = {
  list: () => request<DisclosurePolicyRead[]>("/api/v1/disclosure-policies", authed()),
};

// --- Audit log ---------------------------------------------------------------

export interface AuditListParams {
  entityType?: string;
  entityId?: string;
  action?: string;
  actorId?: string;
  actorType?: string;
  createdFrom?: string;
  createdTo?: string;
  limit?: number;
  offset?: number;
}

export const auditApi = {
  list: (params: AuditListParams = {}) =>
    request<Paginated<AuditLogDiff>>(
      "/api/v1/audit-logs",
      authed({
        query: {
          entity_type: params.entityType,
          entity_id: params.entityId,
          action: params.action,
          actor_id: params.actorId,
          actor_type: params.actorType,
          created_from: params.createdFrom,
          created_to: params.createdTo,
          limit: params.limit ?? 50,
          offset: params.offset ?? 0,
        },
      }),
    ),
};

// --- Query keys --------------------------------------------------------------

/**
 * Centralised TanStack Query keys.
 *
 * Kept in one place so an invalidation cannot miss a cache entry because two call
 * sites spelled the same key differently.
 */
export const queryKeys = {
  me: ["me"] as const,
  influencers: (params: InfluencerListParams) => ["influencers", params] as const,
  influencer: (id: string) => ["influencer", id] as const,
  influencerVersions: (id: string) => ["influencer", id, "versions"] as const,
  influencerHistory: (id: string) => ["influencer", id, "history"] as const,
  policies: ["disclosure-policies"] as const,
  auditLogs: (params: AuditListParams) => ["audit-logs", params] as const,
};
