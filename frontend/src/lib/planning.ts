// Tasks, recurring work and renewals (backend/app/planning.py): what's coming up
// for a customer.

/** A rhythm: every so many weeks or months. */
export interface Every {
  count: number;
  unit: "weeks" | "months";
}

export interface Who {
  id: number;
  display_name: string;
}

/** Who a task or a renewal's warning is for. */
export type Audience = "people" | "technicians" | "managers";

export interface Task {
  id: number;
  title: string;
  /** What to do, or what's special. */
  notes: string;
  due_on: string;
  audience: Audience;
  people: Who[];
  service_id: number | null;
  service: string | null;
  system_id: number | null;
  system: string | null;
  ticket: string;
  /** A recurring task's rhythm. */
  every: Every | null;
  /** The renewal it was made by. */
  renewal_id: number | null;
  /** Its maker, or someone who manages customers. */
  may_remove: boolean;
}

export type RenewalKind =
  | "licence" | "antivirus" | "feature_key" | "certificate" | "warranty" | "subscription" | "domain" | "other";
export type Decision = "" | "approved" | "waiting" | "renewed" | "declined";
export type Reason = "declined" | "not_approved" | "no_answer" | "not_paid";

export interface Renewal {
  id: number;
  what: string;
  kind: RenewalKind;
  renews_on: string;
  every: Every | null;
  /** How many days before to warn, and whom. */
  warn_days: number;
  audience: Audience;
  people: number[];
  who: Who[];
  service_id: number | null;
  service: string | null;
  system_id: number | null;
  system: string | null;
  supplier: string;
  notes: string;
  decision: Decision;
  /** Why it won't be renewed, and what must be done before it runs out. */
  reason: Reason | "";
  fallback: string;
}

export const RENEWAL_KINDS: Record<RenewalKind, string> = {
  licence: "Licence",
  antivirus: "Antivirus",
  feature_key: "Feature key",
  certificate: "Certificate",
  warranty: "Warranty",
  subscription: "Subscription",
  domain: "Domain",
  other: "Other",
};

/** The decision words are fixed: never "Renew" alone. */
export const DECISIONS: Record<Exclude<Decision, "">, string> = {
  approved: "Approved",
  waiting: "Waiting for the customer",
  renewed: "Renewed",
  declined: "Won't be renewed",
};

export const REASONS: Record<Reason, string> = {
  declined: "The customer declined",
  not_approved: "It wasn't approved",
  no_answer: "The customer didn't answer",
  not_paid: "It wasn't paid",
};

export const AUDIENCES: Record<Audience, string> = {
  technicians: "The customer's technicians",
  managers: "The Managers",
  people: "Named people",
};

/** Today in the viewer's time zone, as a plain date: "2026-11-18". */
export function today(now = new Date()): string {
  const local = new Date(now.getTime() - now.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 10);
}

const DAY_MS = 86_400_000;

/** A plain date some days on. */
export function addDays(day: string, days: number): string {
  return new Date(Date.parse(day) + days * DAY_MS).toISOString().slice(0, 10);
}

/** Whole days from one plain date to another; negative when it's earlier. */
export function daysBetween(from: string, to: string): number {
  return Math.round((Date.parse(to) - Date.parse(from)) / DAY_MS);
}

/** The day one interval later; a month's end stays in its month (31 Jan + 1 month
 *  is 28 or 29 Feb), as the backend counts it. */
export function addInterval(day: string, every: Every): string {
  if (every.unit === "weeks") return addDays(day, 7 * every.count);
  const [year, month, dayOfMonth] = day.split("-").map(Number);
  const months = month - 1 + every.count;
  const last = new Date(Date.UTC(year + Math.floor(months / 12), (months % 12) + 1, 0)).getUTCDate();
  return new Date(Date.UTC(year + Math.floor(months / 12), months % 12, Math.min(dayOfMonth, last)))
    .toISOString().slice(0, 10);
}

/** "Every 3 months", "Every week", "Every year". */
export function rhythm(every: Every): string {
  if (every.unit === "months" && every.count % 12 === 0) {
    return every.count === 12 ? "Every year" : `Every ${every.count / 12} years`;
  }
  const unit = every.unit === "weeks" ? "week" : "month";
  return every.count === 1 ? `Every ${unit}` : `Every ${every.count} ${unit}s`;
}

/** How pressing a date is: red when it's passed, yellow within a week. */
export function dueTone(day: string, now = today()): "critical" | "warning" | "neutral" {
  const left = daysBetween(now, day);
  return left < 0 ? "critical" : left <= 7 ? "warning" : "neutral";
}

/** "Overdue by 3 days", "Today", "Tomorrow", "In 12 days". */
export function dueWords(day: string, now = today()): string {
  const left = daysBetween(now, day);
  if (left < -1) return `Overdue by ${-left} days`;
  if (left === -1) return "Overdue by 1 day";
  if (left === 0) return "Today";
  if (left === 1) return "Tomorrow";
  return `In ${left} days`;
}

/** A renewal's decision as a pill; an undecided one is open, or overdue once its
 *  date has passed. */
export function decisionPill(
  renewal: Pick<Renewal, "decision" | "renews_on">, now = today(),
): { tone: "ok" | "warning" | "critical"; text: string } {
  if (renewal.decision === "approved" || renewal.decision === "renewed") {
    return { tone: "ok", text: DECISIONS[renewal.decision] };
  }
  if (renewal.decision === "waiting") return { tone: "warning", text: DECISIONS.waiting };
  if (renewal.decision === "declined") return { tone: "critical", text: DECISIONS.declined };
  return renewal.renews_on < now ? { tone: "critical", text: "Overdue, no decision" }
    : { tone: "warning", text: "Renewal open" };
}

/** Who a task is for, or whom a renewal warns. */
export function forWhom(audience: Audience, people: Who[]): string {
  if (audience === "people") return people.map((p) => p.display_name).join(", ") || "Nobody";
  return audience === "managers" ? "The Managers" : "The customer's technicians";
}

/** "Warns the Managers 30 days before". */
export function warnLine(renewal: Pick<Renewal, "warn_days" | "audience" | "who">): string {
  const whom = forWhom(renewal.audience, renewal.who);
  const named = renewal.audience === "people" ? whom : whom.replace(/^The /, "the ");
  return renewal.warn_days === 0 ? `Warns ${named} on the day`
    : `Warns ${named} ${renewal.warn_days} ${renewal.warn_days === 1 ? "day" : "days"} before`;
}

/** Still to deal with: not renewed, and not one that ran out as decided. */
export function renewalOpen(renewal: Pick<Renewal, "decision" | "renews_on">, now = today()): boolean {
  if (renewal.decision === "renewed") return false;
  return !(renewal.decision === "declined" && renewal.renews_on < now);
}

export const emptyTask = (dueOn = today()) => ({
  title: "", notes: "", due_on: dueOn, audience: "technicians" as Audience, people: [] as number[],
  service_id: null as number | null, system_id: null as number | null, ticket: "",
  every: null as Every | null,
});

export const emptyRenewal = (renewsOn = "") => ({
  what: "", kind: "licence" as RenewalKind, renews_on: renewsOn,
  every: { count: 12, unit: "months" } as Every | null, warn_days: 30, audience: "managers" as Audience,
  people: [] as number[], service_id: null as number | null, system_id: null as number | null,
  supplier: "", notes: "",
});
