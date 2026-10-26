export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
    // Why the server refused, when it says (X-Ting-Reason): "session_timed_out",
    // "mfa_required", "step_up_required" and so on. The message is for people.
    readonly reason: string | null = null,
  ) {
    super(message);
  }
}

const FALLBACK = "Something went wrong. Try again.";
const REASON_HEADER = "X-Ting-Reason";

// Kept in memory only, never in localStorage: a script injected into the page
// could read storage, and the token is cheap to fetch again from /api/auth/session.
let csrfToken: string | null = null;

export function setCsrfToken(token: string | null): void {
  csrfToken = token;
}

// Called for every refusal that carries a reason, before the caller sees it, so
// an ended session is handled the same way on every page (see session.svelte.ts).
let refusalHandler: ((error: ApiError) => void) | null = null;

export function onRefusal(handler: (error: ApiError) => void): void {
  refusalHandler = handler;
}

export function messageFrom(status: number, body: unknown): string {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string") return detail;
  if (status === 422) return "Check what you entered and try again.";
  return FALLBACK;
}

type Method = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";

/** A JSON body, or raw bytes such as an uploaded picture. */
export type Body = unknown;

export async function api<T>(
  method: Method,
  path: string,
  body?: Body,
  extraHeaders: Record<string, string> = {},
): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json", ...extraHeaders };
  const raw = body instanceof Blob;
  if (body !== undefined) headers["Content-Type"] = raw ? "application/octet-stream" : "application/json";
  if (method !== "GET" && csrfToken) headers["X-CSRF-Token"] = csrfToken;

  let response: Response;
  try {
    response = await fetch(`/api${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : raw ? body : JSON.stringify(body),
      credentials: "same-origin",
    });
  } catch {
    throw new ApiError(0, "Þing could not be reached. Check your connection and try again.");
  }
  if (response.status === 204) return undefined as T;
  const data: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const error = new ApiError(
      response.status,
      messageFrom(response.status, data),
      response.headers.get(REASON_HEADER),
    );
    if (error.reason) refusalHandler?.(error);
    throw error;
  }
  return data as T;
}

/** Whether the error is an ended session, already dealt with by the refusal handler. */
export function sessionGone(error: unknown): boolean {
  return (
    error instanceof ApiError &&
    error.status === 401 &&
    (error.reason?.startsWith("session_") || error.reason === "signed_out")
  );
}
