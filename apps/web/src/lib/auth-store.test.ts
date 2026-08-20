import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { readSession, useSessionHydrated, useSessionStore } from "@/lib/auth-store";

/**
 * Regression guard for "pressing F5 signs you out".
 *
 * On a hard page load the store starts empty and `persist` fills it from
 * `localStorage` a moment later. The route guard in `AppShell` redirects when it
 * sees no token, so if it is allowed to decide during that moment it sends a
 * signed-in user to /login — with the token still sitting in storage.
 *
 * These tests pin the mechanism rather than the symptom: the hook must report the
 * persist middleware's real hydration state and must learn about a change through
 * its subscription. A `useState(false)` that never updates, or a hook that simply
 * returns `true`, fails here.
 */
afterEach(() => {
  vi.restoreAllMocks();
});

describe("useSessionHydrated", () => {
  it("reports not-hydrated before rehydration finishes", () => {
    vi.spyOn(useSessionStore.persist, "hasHydrated").mockReturnValue(false);

    const { result } = renderHook(() => useSessionHydrated());

    expect(result.current).toBe(false);
  });

  it("updates when rehydration finishes", () => {
    let notify: (() => void) | undefined;
    vi.spyOn(useSessionStore.persist, "onFinishHydration").mockImplementation((listener) => {
      notify = () => listener(useSessionStore.getState());
      return () => {};
    });
    const hasHydrated = vi.spyOn(useSessionStore.persist, "hasHydrated").mockReturnValue(false);

    const { result } = renderHook(() => useSessionHydrated());
    expect(result.current).toBe(false);

    hasHydrated.mockReturnValue(true);
    act(() => notify?.());

    expect(result.current).toBe(true);
  });

  it("reports hydrated for the real store, so a reload is not a sign-out", async () => {
    localStorage.setItem(
      "influenceros.session",
      JSON.stringify({
        state: { accessToken: "token", refreshToken: "refresh", organizationId: "org" },
        version: 0,
      }),
    );
    await useSessionStore.persist.rehydrate();

    const { result } = renderHook(() => useSessionHydrated());

    expect(result.current).toBe(true);
    expect(readSession().accessToken).toBe("token");

    useSessionStore.getState().clear();
    localStorage.clear();
  });
});
