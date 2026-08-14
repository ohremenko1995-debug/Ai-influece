"use client";

import type { MeRead, TokenPair } from "@influenceros/types";
import { create } from "zustand";
import { persist } from "zustand/middleware";

/**
 * Session state.
 *
 * Zustand is used here — and only here — because this is exactly the "small client
 * UI state" it is meant for: a token pair and the resolved session, needed
 * synchronously by the API client outside of React's render tree. Server data
 * belongs to TanStack Query, never to this store.
 *
 * Tokens live in `localStorage`. For an internal desktop tool that is a deliberate
 * trade: it survives a refresh and works without the API setting cookies on a
 * different origin. The exposure is XSS, which is mitigated by the app rendering
 * no user-supplied HTML and by a short access-token lifetime. httpOnly cookies
 * would be stronger and are the intended upgrade if this ever faces the internet.
 */

const STORAGE_KEY = "influenceros.session";

interface SessionState {
  accessToken: string | null;
  refreshToken: string | null;
  organizationId: string | null;
  /** Resolved on every load from `GET /me`; never persisted. */
  me: MeRead | null;
  setTokens: (tokens: TokenPair) => void;
  setMe: (me: MeRead | null) => void;
  /** Switch the active organization; clears `me` so it is re-fetched. */
  setOrganization: (organizationId: string) => void;
  clear: () => void;
}

export const useSessionStore = create<SessionState>()(
  persist(
    (set) => ({
      accessToken: null,
      refreshToken: null,
      organizationId: null,
      me: null,
      setTokens: (tokens) =>
        set({
          accessToken: tokens.access_token,
          refreshToken: tokens.refresh_token,
          organizationId: tokens.organization_id,
        }),
      setMe: (me) => set({ me }),
      setOrganization: (organizationId) => set({ organizationId, me: null }),
      clear: () => set({ accessToken: null, refreshToken: null, organizationId: null, me: null }),
    }),
    {
      name: STORAGE_KEY,
      // `me` is derived server state: persisting it would show a stale role after a
      // permission change until the next fetch resolved.
      partialize: (state) => ({
        accessToken: state.accessToken,
        refreshToken: state.refreshToken,
        organizationId: state.organizationId,
      }),
    },
  ),
);

/** Snapshot for callers outside React (the API client, route guards). */
export function readSession(): {
  accessToken: string | null;
  refreshToken: string | null;
  organizationId: string | null;
} {
  const { accessToken, refreshToken, organizationId } = useSessionStore.getState();
  return { accessToken, refreshToken, organizationId };
}
