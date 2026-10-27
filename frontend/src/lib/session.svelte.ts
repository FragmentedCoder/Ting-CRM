import { goto } from "$app/navigation";
import { resolve } from "$app/paths";
import { page } from "$app/state";
import { api, ApiError, onRefusal, setCsrfToken } from "./api";
import type { Capability, Role } from "./roles";
import { clearToasts, dismissKey, toast } from "./toast.svelte";

export type Method = "totp" | "webauthn" | "recovery_code";
export type Theme = "system" | "light" | "dark";

export interface SessionInfo {
  user: {
    id: number;
    username: string;
    display_name: string;
    theme: Theme;
    // Null follows the site's colours.
    colours: { primary: string | null; accent: string | null };
    avatar_url: string | null;
    roles: Role[];
    capabilities: Capability[];
  };
  second_factor: "enrol" | "verify" | "done";
  methods: Method[];
  password_change_required: boolean;
  // Only once fully signed in, for someone with multifactor set up.
  recovery_codes_left: number | null;
  csrf_token: string;
  idle_expires_at: string;
  expires_at: string;
  // Only once signed in: which Þing this is.
  version: string | null;
}

export interface SecondFactorResult {
  session: SessionInfo;
  recovery_codes: string[] | null;
}

interface SessionStatus {
  idle_expires_at: string;
  expires_at: string;
}

export const session = $state<{
  current: SessionInfo | null;
  loaded: boolean;
  // A fresh install: every page leads to the setup wizard until it is finished.
  setupNeeded: boolean;
}>({ current: null, loaded: false, setupNeeded: false });

// Goes up each time light or dark is set on the page, so what follows it (the
// colours) is worked out again, also when the change waits for a fade.
export const appearance = $state({ applied: 0 });

/**
 * Light or dark as the user chose; "system" leaves it to the browser's setting.
 * With `fade`, a change you'd see fades slowly across, where the browser can and
 * motion is welcome; otherwise it's instant, as when someone picks it in the app.
 */
export function applyTheme(theme: Theme | undefined, fade = false): void {
  if (typeof document === "undefined") return;
  const root = document.documentElement;
  const systemDark = matchMedia("(prefers-color-scheme: dark)").matches;
  const darkWith = (chosen: string | undefined) =>
    chosen === "dark" || (chosen !== "light" && systemDark);
  const set = () => {
    if (theme === "light" || theme === "dark") root.dataset.theme = theme;
    else delete root.dataset.theme;
    appearance.applied++;
  };
  const changes = darkWith(root.dataset.theme) !== darkWith(theme);
  const calm = matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (fade && changes && !calm && "startViewTransition" in document) document.startViewTransition(set);
  else set();
}

// Where the browser is; nowhere outside one (page can only be read there).
function here(): string {
  return typeof document === "undefined" ? "" : (page.url?.pathname ?? "");
}

// The sign-in screens: someone's own light or dark fades in there as they sign in.
function onSignInScreens(): boolean {
  return here().startsWith("/sign-in") || here().startsWith("/setup");
}

/** `fade`: on the way to or from the sign-in screens, light or dark fades across. */
export function useSession(info: SessionInfo | null, fade = onSignInScreens()): void {
  const before = session.current;
  session.current = info;
  setCsrfToken(info?.csrf_token ?? null);
  applyTheme(info?.user.theme, fade);
  watch(info);
  if (info?.second_factor === "done" && before?.second_factor !== "done") {
    warnAboutRecoveryCodes(info);
  }
}

export async function loadSession(): Promise<SessionInfo | null> {
  try {
    session.setupNeeded = (await api<{ needed: boolean }>("GET", "/setup/status")).needed;
    useSession(await api<SessionInfo>("GET", "/auth/session"));
  } catch (error) {
    if (!(error instanceof ApiError && error.status === 401)) throw error;
    useSession(null);
  } finally {
    session.loaded = true;
  }
  return session.current;
}

export type Place =
  | "/(app)"
  | "/setup"
  | "/sign-in"
  | "/sign-in/set-up"
  | "/sign-in/verify"
  | "/sign-in/new-password";

/**
 * The page a session belongs on. Multifactor already set up comes before a new
 * password; setting it up comes after.
 */
export function placeFor(info: SessionInfo | null, setupNeeded = session.setupNeeded): Place {
  if (setupNeeded) return "/setup";
  if (!info) return "/sign-in";
  if (info.second_factor === "verify") return "/sign-in/verify";
  if (info.password_change_required) return "/sign-in/new-password";
  if (info.second_factor === "enrol") return "/sign-in/set-up";
  return "/(app)";
}

/**
 * Load the session if needed, and move on if this page isn't where it belongs.
 * "app" means any page for someone fully signed in. Returns the session when the
 * page may show (null when it moved on, or for pages for people not signed in).
 */
export async function settle(here: Place | "app"): Promise<SessionInfo | null> {
  const info = session.loaded ? session.current : await loadSession();
  const place = placeFor(info);
  const belongs = here === "app" ? place === "/(app)" : place === here;
  if (!belongs) await goto(resolve(place), { replace: true });
  return belongs ? info : null;
}

export function can(info: SessionInfo | null, capability: Capability): boolean {
  return info?.user.capabilities.includes(capability) ?? false;
}

let leaving: Promise<void> | null = null;

// Found out this long after the session was due to run out, the page (or the
// computer) was asleep.
const LATE_MS = 5 * 60_000;
// A session that ran out, or is gone without a reason: whoever comes back to it
// later finds the sign-in page, which says enough.
const RAN_OUT = ["session_timed_out", "session_expired", "session_ended"];

/**
 * The server ended the session: go straight to the sign-in page, and say why.
 * One that ran out is explained only to someone using Þing here when it did,
 * not on opening Þing again later or coming back to a page that slept through
 * it; what someone else did (an administrator, say) is always told, once.
 * Several requests may find out at once; they share one toast and one move.
 */
export async function sessionEnded(message: string, reason: string): Promise<void> {
  const info = session.current;
  const due = info ? Math.min(Date.parse(info.idle_expires_at), Date.parse(info.expires_at)) : 0;
  const watching = info !== null && Date.now() - due < LATE_MS;
  const tell = watching || !RAN_OUT.includes(reason);
  if (info) clearToasts(); // they were about the session that ended
  useSession(null, true);
  if (tell) toast(message, "warning", { key: "session" });
  if (here() === "/sign-in") return;
  leaving ??= goto(resolve("/sign-in"), { replace: true }).finally(() => (leaving = null));
  await leaving;
}

export async function signOut(): Promise<void> {
  try {
    await api("POST", "/auth/sign-out");
  } catch {
    // Signed out on the server already, or unreachable: forget the session either way.
  }
  useSession(null, true);
  clearToasts();
  await goto(resolve(placeFor(null)), { replace: true });
}

let refreshing: Promise<void> | null = null;

/** Fetch the session again (rights may have changed) and go where it belongs, once
 * however many requests were refused at the same time. */
function refresh(): Promise<void> {
  refreshing ??= reload().finally(() => (refreshing = null));
  return refreshing;
}

async function reload(): Promise<void> {
  session.loaded = false;
  const info = await loadSession();
  const place = placeFor(info);
  const adminGone =
    page.url?.pathname.startsWith("/admin") &&
    !can(info, "administer") &&
    !can(info, "read_audit_log");
  if (place !== "/(app)" || adminGone) await goto(resolve(place), { replace: true });
}

// Every page gets the same answer to a refusal: an ended session goes to the
// sign-in page with the reason; changed rights fetch the session again.
onRefusal((error) => {
  const reason = error.reason ?? "";
  if (error.status === 401 && (reason.startsWith("session_") || (reason === "signed_out" && session.current))) {
    void sessionEnded(error.message, reason);
  } else if (error.status === 403 && ["mfa_required", "password_change_required", "network", "forbidden"].includes(reason)) {
    if (reason === "network" || reason === "forbidden") toast(error.message, "warning", { key: "rights" });
    void refresh();
  }
});

// Watching the session: the browser asks now and then (without counting as
// activity) and right when the session should run out, so an ended session
// goes to the sign-in page by itself instead of on the next click.

const POLL_MS = 60_000;
const WARN_BEFORE_MS = 2 * 60_000;
let pollTimer: ReturnType<typeof setInterval> | undefined;
let deadlineTimer: ReturnType<typeof setTimeout> | undefined;
let warnTimer: ReturnType<typeof setTimeout> | undefined;
// The idle deadline already warned about, so one warning is shown once.
let warnedFor: string | null = null;

function stopWatching(): void {
  clearInterval(pollTimer);
  clearTimeout(deadlineTimer);
  clearTimeout(warnTimer);
  pollTimer = deadlineTimer = warnTimer = undefined;
}

function watch(info: SessionInfo | null): void {
  stopWatching();
  if (typeof window === "undefined" || !info || info.second_factor !== "done") return;
  pollTimer = setInterval(checkStatus, POLL_MS);
  schedule(info);
}

function schedule(status: SessionStatus): void {
  clearTimeout(deadlineTimer);
  clearTimeout(warnTimer);
  const idle = Date.parse(status.idle_expires_at);
  const end = Math.min(idle, Date.parse(status.expires_at));
  const warnAt = idle - WARN_BEFORE_MS;
  deadlineTimer = setTimeout(checkStatus, Math.max(end - Date.now() + 1500, 0));
  if (warnAt > Date.now()) {
    // Kept alive (here or in another tab): any warning is out of date.
    warnedFor = null;
    dismissKey("idle");
  }
  if (idle <= end && warnedFor !== status.idle_expires_at) {
    warnTimer = setTimeout(warnIdle, Math.max(warnAt - Date.now(), 0));
  }
}

async function fetchStatus(): Promise<SessionStatus | null> {
  try {
    return await api<SessionStatus>("GET", "/auth/session/status");
  } catch {
    return null; // an ended session is handled by the refusal handler; offline: next time
  }
}

function useStatus(status: SessionStatus): void {
  if (!session.current) return;
  session.current.idle_expires_at = status.idle_expires_at;
  session.current.expires_at = status.expires_at;
  schedule(status);
}

async function checkStatus(): Promise<void> {
  const status = await fetchStatus();
  if (status) useStatus(status);
}

async function warnIdle(): Promise<void> {
  // Other tabs or requests may have kept it alive meanwhile: ask before warning.
  const status = await fetchStatus();
  if (!status || !session.current) return;
  if (Date.parse(status.idle_expires_at) - WARN_BEFORE_MS <= Date.now()) {
    warnedFor = status.idle_expires_at; // set first, so useStatus doesn't arm it again
    toast("You'll be signed out in two minutes because nothing has happened for a while.", "warning", {
      key: "idle",
      action: { label: "Stay signed in", run: () => void stayActive() },
      // Up until the sign-out, not the usual 30 seconds.
      lifetime: Math.max(Date.parse(status.idle_expires_at) - Date.now(), 1000),
    });
  }
  useStatus(status);
}

async function stayActive(): Promise<void> {
  try {
    const info = await api<SessionInfo>("GET", "/auth/session");
    if (session.current) useSession(info);
  } catch {
    // ended meanwhile: the refusal handler takes over
  }
}

if (typeof document !== "undefined") {
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") void checkStatus();
  });
}

function warnAboutRecoveryCodes(info: SessionInfo): void {
  const left = info.recovery_codes_left;
  if (left === null || left > 3) return;
  const open = { label: "Go to Your account", run: () => void goto(resolve("/(app)/account")) };
  const text =
    left === 0
      ? "You've used your last recovery code. Get new codes in Your account, or set up multifactor again if you've lost your phone or key."
      : `You have ${left} recovery ${left === 1 ? "code" : "codes"} left. Get new ones in Your account.`;
  toast(text, left === 0 ? "critical" : "warning", { key: "recovery-codes", action: open });
}
