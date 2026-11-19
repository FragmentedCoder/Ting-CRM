// Global search (backend/app/search.py): what was found, and where it opens.

import type { CustomerStatus } from "./customers.js";

export type HitKind = "customer" | "company" | "contact" | "site" | "system" | "case";

export interface Hit {
  kind: HitKind;
  customer_id: number;
  customer: string;
  /** None for someone who sees only that the customer exists. */
  status: CustomerStatus | null;
  /** What matched, and a line about it. */
  title: string;
  detail: string;
  /** The customer's page that shows it, and the service or system to open there. */
  page: "overview" | "contacts" | "systems" | "services";
  record_id: number | null;
}

export interface Found {
  hits: Hit[];
  /** More matched than are shown. */
  more: boolean;
}

export const HIT_KINDS: Record<HitKind, string> = {
  customer: "Customer",
  company: "Group company",
  contact: "Contact",
  site: "Site",
  system: "System",
  case: "Case number",
};

/** The shortest search worth sending. */
export const SEARCH_FROM = 2;

/** Where a hit opens, under the customer's own address. */
export function hitPath(hit: Pick<Hit, "page" | "record_id">): { page: string; query: string } {
  if (hit.page === "systems" && hit.record_id !== null) return { page: "/systems", query: `?system=${hit.record_id}` };
  if (hit.page === "services" && hit.record_id !== null) return { page: "/services", query: `?service=${hit.record_id}` };
  return { page: hit.page === "overview" ? "" : `/${hit.page}`, query: "" };
}

/** Whether a key press should open search: Ctrl+K or ⌘K anywhere, "/" outside a field. */
export function opensSearch(
  event: Pick<KeyboardEvent, "key" | "ctrlKey" | "metaKey" | "altKey">, typing: boolean,
): boolean {
  if ((event.ctrlKey || event.metaKey) && !event.altKey && event.key.toLowerCase() === "k") return true;
  return event.key === "/" && !event.ctrlKey && !event.metaKey && !event.altKey && !typing;
}

/** Whether the keyboard is in something that takes typing. */
export function isTyping(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  return target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName);
}
