"use client";

import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useCallback } from "react";

import { meApi, queryKeys } from "@/lib/api";
import { useSessionStore } from "@/lib/auth-store";

/**
 * The resolved session.
 *
 * `GET /me` is the source of truth for role and permissions, not the token. The
 * token proves identity; what the identity may do is re-read from the server, so a
 * role change or a revoked membership takes effect on the next load rather than
 * when the token expires.
 */
export function useSession() {
  const router = useRouter();
  const accessToken = useSessionStore((state) => state.accessToken);
  const storedMe = useSessionStore((state) => state.me);
  const setMe = useSessionStore((state) => state.setMe);
  const clear = useSessionStore((state) => state.clear);

  const query = useQuery({
    queryKey: queryKeys.me,
    queryFn: async () => {
      const me = await meApi.read();
      // Mirrored into the store so non-React callers (route guards) can read it.
      setMe(me);
      return me;
    },
    enabled: Boolean(accessToken),
    staleTime: 60_000,
  });

  const signOut = useCallback(() => {
    clear();
    router.replace("/login");
  }, [clear, router]);

  const me = query.data ?? storedMe;

  return {
    me,
    isLoading: Boolean(accessToken) && query.isLoading && !me,
    isAuthenticated: Boolean(accessToken) && !query.isError,
    error: query.error,
    signOut,
  };
}
