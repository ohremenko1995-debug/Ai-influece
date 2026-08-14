import type { ApiErrorBody } from "@influenceros/types";

/**
 * The single place the browser talks to the API.
 *
 * Everything goes through `request`, so the bearer token, the organization header
 * and the error envelope are handled once. Nothing in `features/` calls `fetch`.
 */

export const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

/** A failed API call, carrying the backend's machine-readable code. */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: Record<string, unknown>;
  readonly requestId: string | null;

  constructor(init: {
    status: number;
    code: string;
    message: string;
    details?: Record<string, unknown>;
    requestId?: string | null;
  }) {
    super(init.message);
    this.name = "ApiError";
    this.status = init.status;
    this.code = init.code;
    this.details = init.details ?? {};
    this.requestId = init.requestId ?? null;
  }

  /** True when re-authenticating could plausibly help. */
  get isAuthFailure(): boolean {
    return this.status === 401;
  }

  get isPermissionDenied(): boolean {
    return this.status === 403;
  }

  get isNotFound(): boolean {
    return this.status === 404;
  }

  /** Domain rules the caller may want to surface differently from a bare error. */
  get isConflict(): boolean {
    return this.status === 409;
  }
}

export interface RequestOptions {
  method?: "GET" | "POST" | "PATCH" | "DELETE";
  body?: unknown;
  /** Repeated values are supported: pass an array. */
  query?: Record<string, string | number | boolean | string[] | undefined | null>;
  accessToken?: string | null;
  organizationId?: string | null;
  signal?: AbortSignal;
}

function buildUrl(path: string, query: RequestOptions["query"]): string {
  const url = new URL(`${API_BASE_URL}${path}`);
  if (query) {
    for (const [key, value] of Object.entries(query)) {
      if (value === undefined || value === null || value === "") continue;
      if (Array.isArray(value)) {
        for (const item of value) url.searchParams.append(key, item);
      } else {
        url.searchParams.set(key, String(value));
      }
    }
  }
  return url.toString();
}

function isErrorBody(value: unknown): value is ApiErrorBody {
  return (
    typeof value === "object" &&
    value !== null &&
    "error" in value &&
    typeof (value as { error: unknown }).error === "object"
  );
}

export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = "GET", body, query, accessToken, organizationId, signal } = options;

  const headers: Record<string, string> = { Accept: "application/json" };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (accessToken) headers.Authorization = `Bearer ${accessToken}`;
  // Sent whenever known, so a user with several memberships never gets an
  // arbitrary default from the backend.
  if (organizationId) headers["X-Organization-Id"] = organizationId;

  let response: Response;
  try {
    response = await fetch(buildUrl(path, query), {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: signal ?? null,
    });
  } catch (cause) {
    // A transport failure is not an API error: there is no status and no code.
    // Reported distinctly so the UI can say "the API is unreachable".
    throw new ApiError({
      status: 0,
      code: "network_error",
      message: "Could not reach the API. Is it running?",
      details: { cause: String(cause) },
    });
  }

  if (response.status === 204) return undefined as T;

  const text = await response.text();
  const payload: unknown = text ? safeJsonParse(text) : null;

  if (!response.ok) {
    if (isErrorBody(payload)) {
      throw new ApiError({
        status: response.status,
        code: payload.error.code,
        message: payload.error.message,
        details: payload.error.details,
        requestId: payload.error.request_id,
      });
    }
    throw new ApiError({
      status: response.status,
      code: "unexpected_response",
      message: `Request failed with status ${response.status}`,
      requestId: response.headers.get("X-Request-ID"),
    });
  }

  return payload as T;
}

function safeJsonParse(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}

/**
 * Human-readable message for any thrown value.
 *
 * Used by every error boundary, so an unexpected non-Error rejection still shows
 * something more useful than "[object Object]".
 */
export function describeError(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return "An unexpected error occurred";
}

export function requestIdOf(error: unknown): string | null {
  return error instanceof ApiError ? error.requestId : null;
}
