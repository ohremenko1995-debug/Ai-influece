"use client";

import type { MeRead, TokenPair } from "@influenceros/types";
import { useSyncExternalStore } from "react";
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

/**
 * Whether the persisted session has been read back from `localStorage` yet.
 *
 * This is load-bearing, not a nicety. On a hard page load the store starts with
 * `accessToken: null` and is rehydrated a tick later. A route guard that decides
 * during that tick sees "no token" and redirects a signed-in user to /login — so
 * pressing F5, or opening a deep link, would sign the user out even though the
 * token is sitting in `localStorage`.
 *
 * `useSyncExternalStore` rather than an effect that calls `setState`: hydration is
 * external state, the server snapshot is `false` so the first render matches the
 * prerender, and React re-reads the snapshot after subscribing — which is what
 * covers the common case where rehydration already finished before this component
 * mounted and no event will ever arrive.
 */
export function useSessionHydrated(): boolean {
  return useSyncExternalStore(
    (onStoreChange) => useSessionStore.persist.onFinishHydration(onStoreChange),
    () => useSessionStore.persist.hasHydrated(),
    () => false,
  );
}

/** Snapshot for callers outside React (the API client, route guards). */
export function readSession(): {
  accessToken: string | null;
  refreshToken: string | null;
  organizationId: string | null;
} {
  const { accessToken, refreshToken, organizationId } = useSessionStore.getState();
  return { accessToken, refreshToken, organizationId };
}
