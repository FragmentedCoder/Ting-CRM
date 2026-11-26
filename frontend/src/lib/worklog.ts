// The work log (backend/app/worklog.py): what was done for a customer.

export type LogKind = "call" | "work" | "visit" | "meeting" | "email" | "document";

export interface LogEntry {
  id: number;
  kind: LogKind;
  happened_at: string;
  author_id: number | null;
  author: string | null;
  text: string;
  service_id: number | null;
  service: string | null;
  system_ids: number[];
  systems: string[];
  case_number: string;
  /** As it was when logged: covered by an agreement, billable, or no service. */
  coverage: "covered" | "billable" | "";
  on_site: boolean;
  ticket: string;
  /** Its author, or someone who manages customers. */
  may_change: boolean;
}

export interface LogPage {
  entries: LogEntry[];
  /** How many match the filters, and how many the customer has in all. */
  total: number;
  total_logged: number;
  /** The last 90 days, whatever the filters. */
  summary: { entries: number; on_site: number; people: number; billable: number; by_service: [string, number][] };
}

export const LOG_KINDS: Record<LogKind, string> = {
  call: "Call",
  work: "Work",
  visit: "Visit",
  meeting: "Meeting",
  email: "Email",
  document: "Document",
};

/** The kinds someone logs by hand; emails and documents arrive by upload. */
export const LOGGED_KINDS: LogKind[] = ["work", "call", "visit", "meeting"];

const DAY = new Intl.DateTimeFormat("en-GB", { weekday: "long", day: "numeric", month: "long", year: "numeric" });
const HOUR = new Intl.DateTimeFormat("en-GB", { hour: "2-digit", minute: "2-digit" });

/** "14:05" in the viewer's time zone. */
export function hourMinute(iso: string): string {
  return HOUR.format(new Date(iso));
}

/** Entries under the day they happened on (in the viewer's time zone), in the order given. */
export function byDay(entries: LogEntry[]): { day: string; entries: LogEntry[] }[] {
  const days: { day: string; entries: LogEntry[] }[] = [];
  for (const entry of entries) {
    const day = DAY.format(new Date(entry.happened_at));
    const last = days.at(-1);
    if (last?.day === day) last.entries.push(entry);
    else days.push({ day, entries: [entry] });
  }
  return days;
}

/** A moment as a datetime-local input takes it: "2026-10-27T14:05" in local time. */
export function toLocalInput(moment: Date): string {
  const local = new Date(moment.getTime() - moment.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 16);
}

/** "AF" for "Astrid Fjeld": the initials shown beside an entry. */
export function initials(name: string | null): string {
  const parts = (name ?? "").trim().split(/\s+/).filter(Boolean);
  return ((parts[0]?.[0] ?? "?") + (parts.length > 1 ? parts.at(-1)![0] : "")).toUpperCase();
}
