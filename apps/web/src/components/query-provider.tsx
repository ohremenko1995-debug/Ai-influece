"use client";

import { QueryCache, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";

import { ApiError } from "@/lib/api-client";
import { useSessionStore } from "@/lib/auth-store";

/**
 * TanStack Query provider.
 *
 * The client is created inside state so each browser session gets its own — a
 * module-level client would be shared across requests during server rendering and
 * leak one user's cache into another's response.
 */
export function QueryProvider({ children }: { children: ReactNode }) {
  const clear = useSessionStore((state) => state.clear);

  const [client] = useState(
    () =>
      new QueryClient({
        queryCache: new QueryCache({
          onError: (error) => {
            // A rejected token is not a transient failure: drop the session so the
            // route guard sends the user to the login screen instead of looping on
            // 401s.
            if (error instanceof ApiError && error.isAuthFailure) clear();
          },
        }),
        defaultOptions: {
          queries: {
            staleTime: 30_000,
            gcTime: 5 * 60_000,
            refetchOnWindowFocus: false,
            retry: (failureCount, error) => {
              // Retrying an authorization or validation failure cannot succeed; it
              // only delays the error the user needs to see.
              if (error instanceof ApiError && error.status >= 400 && error.status < 500) {
                return false;
              }
              return failureCount < 2;
            },
          },
          mutations: {
            // A mutation is a side effect. Repeating one automatically risks doing
            // it twice, so failures surface to the user instead.
            retry: false,
          },
        },
      }),
  );

  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
