import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { session, sessionEnded, useSession, type SessionInfo } from "./session.svelte";
import { dismiss, toasts } from "./toast.svelte";

vi.mock("$app/navigation", () => ({ goto: vi.fn(async () => {}) }));

const NOW = Date.parse("2026-10-24T12:00:00Z");
const LATER = "2026-10-25T00:00:00Z";

function signedIn(idleExpiresAt: string): SessionInfo {
  return {
    user: {
      id: 1, username: "astrid", display_name: "Astrid Fjeld", theme: "system",
      colours: { primary: null, accent: null }, avatar_url: null, roles: [], capabilities: [],
    },
    second_factor: "done",
    methods: [],
    password_change_required: false,
    recovery_codes_left: null,
    csrf_token: "t",
    idle_expires_at: idleExpiresAt,
    expires_at: LATER,
    version: null,
  };
}

function statusAnswers(idleExpiresAt: () => string) {
  const fetch = vi.fn(async () =>
    new Response(JSON.stringify({ idle_expires_at: idleExpiresAt(), expires_at: LATER }), {
      status: 200,
    }),
  );
  vi.stubGlobal("fetch", fetch);
  return fetch;
}

beforeEach(() => {
  vi.useFakeTimers({ now: NOW });
  vi.stubGlobal("window", {}); // the watcher only runs in a browser
});

afterEach(() => {
  useSession(null);
  for (const item of [...toasts]) dismiss(item.id);
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("the idle warning", () => {
  it("shows once, and doesn't keep asking the server", async () => {
    const idle = new Date(NOW + 90_000).toISOString(); // already inside the last two minutes
    const fetch = statusAnswers(() => idle);
    useSession(signedIn(idle));

    await vi.advanceTimersByTimeAsync(20_000);

    expect(fetch.mock.calls.length).toBeLessThanOrEqual(2);
    expect(toasts.filter((t) => t.key === "idle")).toHaveLength(1);
  });

  it("waits until two minutes before the sign-out", async () => {
    const idle = new Date(NOW + 30 * 60_000).toISOString();
    statusAnswers(() => idle);
    useSession(signedIn(idle));

    await vi.advanceTimersByTimeAsync(27 * 60_000);
    expect(toasts.filter((t) => t.key === "idle")).toHaveLength(0);
    await vi.advanceTimersByTimeAsync(2 * 60_000);
    expect(toasts.filter((t) => t.key === "idle")).toHaveLength(1);
  });

  it("goes away when you stay signed in, and comes back only before the new deadline", async () => {
    let idle = new Date(NOW + 90_000).toISOString();
    const fetch = vi.fn(async (url: string) => {
      const body = url.endsWith("/status")
        ? { idle_expires_at: idle, expires_at: LATER }
        : signedIn(idle);
      return new Response(JSON.stringify(body), { status: 200 });
    });
    vi.stubGlobal("fetch", fetch);
    useSession(signedIn(idle));
    await vi.advanceTimersByTimeAsync(1_000);
    const warning = toasts.find((t) => t.key === "idle");
    expect(warning?.action?.label).toBe("Stay signed in");

    idle = new Date(Date.now() + 30 * 60_000).toISOString(); // the server counts the click
    warning?.action?.run();
    await vi.advanceTimersByTimeAsync(1_000);
    expect(toasts.filter((t) => t.key === "idle")).toHaveLength(0);

    await vi.advanceTimersByTimeAsync(27 * 60_000);
    expect(toasts.filter((t) => t.key === "idle")).toHaveLength(0);
    await vi.advanceTimersByTimeAsync(2 * 60_000);
    expect(toasts.filter((t) => t.key === "idle")).toHaveLength(1);
  });
});

describe("an ended session", () => {
  const told = () => toasts.filter((t) => t.key === "session").map((t) => t.text);

  it("is explained to someone using Þing when it ends", async () => {
    useSession(signedIn(LATER));
    await sessionEnded("An administrator signed you out.", "session_by_admin");
    expect(told()).toEqual(["An administrator signed you out."]);
    expect(session.current).toBeNull();
  });

  it("is explained just after it ran out, as the page found out by itself", async () => {
    useSession(signedIn("2026-10-24T11:59:58Z"));
    await sessionEnded("You were signed out after 30 minutes without activity.", "session_timed_out");
    expect(told()).toHaveLength(1);
  });

  it("isn't, long after it ran out: the page or the computer slept through it", async () => {
    useSession(signedIn("2026-10-24T09:00:00Z"));
    await sessionEnded("Your session has ended. Sign in again to continue.", "session_ended");
    expect(told()).toHaveLength(0);
    expect(session.current).toBeNull();
  });

  it("isn't, opening Þing again later after it ran out", async () => {
    for (const reason of ["session_ended", "session_timed_out", "session_expired"]) {
      await sessionEnded("Your session has ended. Sign in again to continue.", reason);
    }
    expect(told()).toHaveLength(0);
  });

  it("is, whenever someone else ended it: that's told once, however late", async () => {
    await sessionEnded("An administrator reset your multifactor authentication.", "session_mfa_reset");
    expect(told()).toHaveLength(1);
    useSession(signedIn("2026-10-24T09:00:00Z"));
    await sessionEnded("An administrator signed you out.", "session_by_admin");
    expect(told()).toEqual(["An administrator signed you out."]);
  });

  it("is told once when several requests find out at once", async () => {
    useSession(signedIn(LATER));
    await Promise.all([1, 2, 3].map(() => sessionEnded("Ended.", "session_by_admin")));
    expect(told()).toEqual(["Ended."]);
  });
});
