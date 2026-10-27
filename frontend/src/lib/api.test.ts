import { afterEach, describe, expect, it, vi } from "vitest";
import { api, ApiError, messageFrom, onRefusal, sessionGone, setCsrfToken } from "./api";

function respond(status: number, body?: unknown, headers: Record<string, string> = {}) {
  const fetch = vi.fn().mockResolvedValue(
    new Response(body === undefined ? null : JSON.stringify(body), { status, headers }),
  );
  vi.stubGlobal("fetch", fetch);
  return fetch;
}

afterEach(() => {
  vi.unstubAllGlobals();
  setCsrfToken(null);
});

describe("api", () => {
  it("sends the CSRF token on writes, never on reads", async () => {
    setCsrfToken("token-123");
    const fetch = respond(200, {});

    await api("POST", "/auth/sign-out");
    await api("GET", "/auth/session");

    expect(fetch.mock.calls[0][1].headers["X-CSRF-Token"]).toBe("token-123");
    expect(fetch.mock.calls[1][1].headers["X-CSRF-Token"]).toBeUndefined();
  });

  it("sends JSON bodies to /api", async () => {
    const fetch = respond(200, { ok: true });
    await api("POST", "/auth/sign-in", { username: "astrid" });

    const [url, init] = fetch.mock.calls[0];
    expect(url).toBe("/api/auth/sign-in");
    expect(init.headers["Content-Type"]).toBe("application/json");
    expect(JSON.parse(init.body)).toEqual({ username: "astrid" });
  });

  it("turns a refusal into an ApiError carrying the server's message", async () => {
    respond(401, { detail: "Sign-in failed." });
    await expect(api("POST", "/auth/sign-in", {})).rejects.toEqual(
      new ApiError(401, "Sign-in failed."),
    );
  });

  it("explains an unreachable server in plain words", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    await expect(api("GET", "/auth/session")).rejects.toMatchObject({
      status: 0,
      message: expect.stringContaining("could not be reached"),
    });
  });

  it("passes on why the server refused, and tells the refusal handler first", async () => {
    const seen: ApiError[] = [];
    onRefusal((error) => seen.push(error));
    respond(401, { detail: "You were signed out." }, { "X-Ting-Reason": "session_timed_out" });

    const error = await api("GET", "/account").catch((e: unknown) => e);
    expect(error).toMatchObject({ status: 401, reason: "session_timed_out" });
    expect(seen).toEqual([error]);
    expect(sessionGone(error)).toBe(true);
  });

  it("leaves refusals without a reason, like a wrong password, to the page", async () => {
    const seen: ApiError[] = [];
    onRefusal((error) => seen.push(error));
    respond(401, { detail: "Sign-in failed." });
    const error = await api("POST", "/auth/sign-in", {}).catch((e: unknown) => e);
    expect(seen).toEqual([]);
    expect(sessionGone(error)).toBe(false);
  });

  it("sends a picture as raw bytes", async () => {
    const fetch = respond(200, {});
    const picture = new Blob([new Uint8Array([137, 80, 78, 71])], { type: "image/png" });
    await api("PUT", "/account/avatar", picture);
    const [, init] = fetch.mock.calls[0];
    expect(init.headers["Content-Type"]).toBe("application/octet-stream");
    expect(init.body).toBe(picture);
  });

  it("returns nothing for 204 No Content", async () => {
    respond(204);
    await expect(api("POST", "/auth/sign-out")).resolves.toBeUndefined();
  });
});

describe("messageFrom", () => {
  it.each([
    [400, { detail: "That didn't work." }, "That didn't work."],
    [422, { detail: [{ loc: ["body"], msg: "x" }] }, "Check what you entered and try again."],
    [500, null, "Something went wrong. Try again."],
  ])("status %i", (status, body, message) => {
    expect(messageFrom(status, body)).toBe(message);
  });
});
