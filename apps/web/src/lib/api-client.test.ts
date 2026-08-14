import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, describeError, request, requestIdOf } from "./api-client";

function jsonResponse(body: unknown, init: ResponseInit = {}): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
    ...init,
  });
}

describe("request", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("sends the bearer token and the organization header when both are known", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ ok: true }));
    vi.stubGlobal("fetch", fetchMock);

    await request("/api/v1/influencers", {
      accessToken: "token-abc",
      organizationId: "org-123",
    });

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    const headers = init.headers as Record<string, string>;
    expect(headers.Authorization).toBe("Bearer token-abc");
    expect(headers["X-Organization-Id"]).toBe("org-123");
  });

  it("omits the organization header when no organization is selected", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ ok: true }));
    vi.stubGlobal("fetch", fetchMock);

    await request("/api/v1/me", { accessToken: "token-abc", organizationId: null });

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(init.headers as Record<string, string>).not.toHaveProperty("X-Organization-Id");
  });

  it("serialises repeated query values as repeated parameters", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ items: [] }));
    vi.stubGlobal("fetch", fetchMock);

    await request("/api/v1/influencers", {
      query: { status: ["draft", "active"], limit: 10 },
    });

    const [url] = fetchMock.mock.calls[0] as [string];
    const params = new URL(url).searchParams;
    expect(params.getAll("status")).toEqual(["draft", "active"]);
    expect(params.get("limit")).toBe("10");
  });

  it("drops empty and nullish query values rather than sending blanks", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ items: [] }));
    vi.stubGlobal("fetch", fetchMock);

    await request("/api/v1/influencers", {
      query: { search: "", niche: undefined, market: null, limit: 50 },
    });

    const [url] = fetchMock.mock.calls[0] as [string];
    const params = new URL(url).searchParams;
    expect([...params.keys()]).toEqual(["limit"]);
  });

  it("unwraps the API error envelope into an ApiError", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse(
          {
            error: {
              code: "invalid_transition",
              message: "Influencer cannot move from 'archived' to 'active'",
              details: { current_status: "archived" },
              request_id: "req-1",
            },
          },
          { status: 409 },
        ),
      ),
    );

    const error = await request("/api/v1/influencers/x/status", { method: "POST" }).catch(
      (caught: unknown) => caught,
    );

    expect(error).toBeInstanceOf(ApiError);
    const apiError = error as ApiError;
    expect(apiError.status).toBe(409);
    expect(apiError.code).toBe("invalid_transition");
    expect(apiError.isConflict).toBe(true);
    expect(apiError.details).toEqual({ current_status: "archived" });
    expect(apiError.requestId).toBe("req-1");
  });

  it.each([
    [401, "isAuthFailure"],
    [403, "isPermissionDenied"],
    [404, "isNotFound"],
  ] as const)("classifies %i responses", async (status, flag) => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          jsonResponse(
            { error: { code: "x", message: "m", details: {}, request_id: null } },
            { status },
          ),
        ),
    );

    const error = (await request("/api/v1/me").catch((caught: unknown) => caught)) as ApiError;
    expect(error[flag]).toBe(true);
  });

  it("reports a transport failure distinctly from an API error", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));

    const error = (await request("/api/v1/me").catch((caught: unknown) => caught)) as ApiError;
    expect(error.status).toBe(0);
    expect(error.code).toBe("network_error");
    // The user needs to know the API is unreachable, not read a TypeError.
    expect(error.message).toContain("Could not reach the API");
  });

  it("falls back to a generic error when the body is not an envelope", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response("<html>502 Bad Gateway</html>", {
          status: 502,
          headers: { "X-Request-ID": "req-gateway" },
        }),
      ),
    );

    const error = (await request("/api/v1/me").catch((caught: unknown) => caught)) as ApiError;
    expect(error.code).toBe("unexpected_response");
    expect(error.requestId).toBe("req-gateway");
  });

  it("returns undefined for a 204 without trying to parse a body", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 204 })));
    await expect(request("/api/v1/thing", { method: "DELETE" })).resolves.toBeUndefined();
  });
});

describe("describeError", () => {
  it("uses the API message when present", () => {
    const error = new ApiError({ status: 403, code: "permission_denied", message: "Nope" });
    expect(describeError(error)).toBe("Nope");
    expect(requestIdOf(error)).toBeNull();
  });

  it("handles a thrown non-Error without producing [object Object]", () => {
    expect(describeError({ weird: true })).toBe("An unexpected error occurred");
  });
});
