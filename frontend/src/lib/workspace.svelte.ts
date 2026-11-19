import { api } from "./api.js";
import type { CustomerSummary } from "./customers.js";

// What the side menu works from: the customers someone can pick and the one that's
// open. Only customers' IDs are remembered on this device (the one that's open, and
// the last few looked at), never their names.

const REMEMBERED = "ting.customer";
const RECENT = "ting.recent";
const RECENT_KEPT = 6;

export const workspace = $state<{
  customers: CustomerSummary[] | null;
  customerId: number | null;
  // Goes up on every refresh, so open pages can check they're still allowed.
  checks: number;
  // The customers looked at last, the latest first, by ID.
  recent: number[];
}>({ customers: null, customerId: null, checks: 0, recent: [] });

let lastRefresh = 0;

export function openCustomer(): CustomerSummary | null {
  return workspace.customers?.find((c) => c.id === workspace.customerId) ?? null;
}

function remember(id: number | null): void {
  try {
    if (id === null) localStorage.removeItem(REMEMBERED);
    else localStorage.setItem(REMEMBERED, String(id));
  } catch {
    // Private windows and blocked storage: the menu just starts without a customer.
  }
}

function remembered(): number | null {
  try {
    const id = Number(localStorage.getItem(REMEMBERED));
    return Number.isInteger(id) && id > 0 ? id : null;
  } catch {
    return null;
  }
}

function recentIds(): number[] {
  try {
    const ids: unknown = JSON.parse(localStorage.getItem(RECENT) ?? "[]");
    return Array.isArray(ids) ? ids.filter((id) => Number.isInteger(id) && id > 0).slice(0, RECENT_KEPT) : [];
  } catch {
    return [];
  }
}

/** A customer was opened: it goes first among the recently viewed. */
export function noteViewed(id: number): void {
  const before = workspace.recent.length ? workspace.recent : recentIds();
  workspace.recent = [id, ...before.filter((seen) => seen !== id)].slice(0, RECENT_KEPT);
  try {
    localStorage.setItem(RECENT, JSON.stringify(workspace.recent));
  } catch {
    // Private windows and blocked storage: it's kept for this visit only.
  }
}

/** The recently viewed customers someone may still open, the latest first. */
export function recentCustomers(): CustomerSummary[] {
  const listed = workspace.customers ?? [];
  return workspace.recent.map((id) => listed.find((c) => c.id === id)).filter((c) => c !== undefined);
}

/** Fetch the customers again (names, counts). */
export async function refreshWorkspace(): Promise<void> {
  lastRefresh = Date.now();
  const found = await api<CustomerSummary[]>("GET", "/customers").catch(() => null);
  // A failed request (offline, signed out) keeps what's there rather than emptying it.
  if (found === null && workspace.customers !== null) return;
  workspace.customers = found ?? [];
  if (workspace.customerId === null) workspace.customerId = remembered();
  if (!workspace.recent.length) workspace.recent = recentIds();
  if (workspace.customerId !== null && !openCustomer()) workspace.customerId = null;
  workspace.checks++;
}

/** Refresh unless that happened in the last few seconds (as on every page change). */
export function refreshSoon(): void {
  if (Date.now() - lastRefresh > 15_000) void refreshWorkspace();
}

/**
 * Notice access that changed while the app is open (someone unassigned you, a
 * customer was deleted): refresh every minute while the page is in view, and on
 * coming back to it. Returns the function that stops watching.
 */
export function watchWorkspace(): () => void {
  const visible = () => {
    if (document.visibilityState === "visible") refreshSoon();
  };
  const timer = setInterval(() => {
    if (document.visibilityState === "visible") void refreshWorkspace();
  }, 60_000);
  document.addEventListener("visibilitychange", visible);
  window.addEventListener("focus", visible);
  return () => {
    clearInterval(timer);
    document.removeEventListener("visibilitychange", visible);
    window.removeEventListener("focus", visible);
  };
}

/** Open a customer in the menu (and remember it). */
export async function chooseCustomer(id: number | null) {
  workspace.customerId = id;
  remember(id);
  // A customer the list doesn't know yet (just added, or newly assigned) fetches it again.
  if (workspace.customers === null || (id !== null && !openCustomer())) await refreshWorkspace();
}

/** Forget everything about the workspace, as on signing out. */
export function clearWorkspace(): void {
  workspace.customers = null;
  workspace.customerId = null;
  workspace.recent = [];
}
