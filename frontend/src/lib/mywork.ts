// My work (backend/app/mywork.py): where the day starts.

import { date } from "./format.js";
import { daysBetween, type Decision, type Task } from "./planning.js";

export interface MyTask {
  customer_id: number;
  customer: string;
  task: Task;
}

/** A renewal, or an agreement's last notice day or its end. */
export interface Dated {
  customer_id: number;
  customer: string;
  kind: "renewal" | "notice" | "ends" | "renews";
  what: string;
  day: string;
  decision: Decision | null;
}

export interface Reason {
  kind: "tasks_overdue" | "renewal_overdue" | "renewal_soon" | "notice" | "uncovered";
  tone: "critical" | "warning";
  /** How many, and the first one's name and day. */
  count: number;
  what: string;
  day: string | null;
}

/** One row of All customers (backend/app/attention.py): its services, and what
 *  needs attention. */
export interface CustomerStanding {
  customer_id: number;
  /** Active services, and how many of them no agreement covers. */
  services: number;
  uncovered: number;
  reasons: Reason[];
  more: number;
}

/** "3 · 1 without agreement": a customer's services in a table cell. */
export function servicesWords(standing: Pick<CustomerStanding, "services" | "uncovered">): {
  count: string;
  uncovered: string | null;
} {
  return {
    count: standing.services ? String(standing.services) : "None yet",
    uncovered: standing.uncovered ? `${standing.uncovered} without agreement` : null,
  };
}

export interface Attention {
  customer_id: number;
  customer: string;
  /** The most urgent, at most three. */
  reasons: Reason[];
  more: number;
}

export interface MyWork {
  today: string;
  /** How far ahead what's coming up reaches (the team's setting), the last day
   *  within it, and how many of my tasks are due later than that. */
  ahead_months: number;
  ahead_until: string;
  later: number;
  tasks: MyTask[];
  dates: Dated[];
  attention: Attention[];
  counts: { overdue: number; this_week: number; dates: number; attention: number };
  /** What's the Managers' to deal with. */
  managers: {
    waiting: Dated[];
    monthly_cases: { customer_id: number; customer: string; service: string; case_number: string; since: string | null }[];
    uncovered: { customer_id: number; customer: string; services: string[] }[];
  } | null;
}

export const DATED_KINDS: Record<Dated["kind"], string> = {
  renewal: "Renewal",
  notice: "Last notice day",
  ends: "Agreement ends",
  renews: "Agreement renews",
};

/** Why a customer needs attention, in a few words. */
export function reasonWords(reason: Reason, now: string): string {
  const several = reason.count > 1;
  switch (reason.kind) {
    case "tasks_overdue":
      return several ? `${reason.count} tasks overdue` : "1 task overdue";
    case "renewal_overdue":
      return several ? `${reason.count} renewals overdue` : `Renewal overdue: ${reason.what}`;
    case "renewal_soon": {
      if (several) return `${reason.count} renewals within 30 days`;
      const left = reason.day ? daysBetween(now, reason.day) : 0;
      const when = left === 0 ? "today" : left === 1 ? "tomorrow" : `in ${left} days`;
      return `Renewal ${when}: ${reason.what}`;
    }
    case "notice":
      return several ? `${reason.count} notice days within 60 days` : `Notice by ${date(reason.day)}: ${reason.what}`;
    case "uncovered":
      return several ? `${reason.count} services without agreement` : `No agreement: ${reason.what}`;
  }
}

/** "Good morning", by the viewer's clock. */
export function greeting(now = new Date()): string {
  const hour = now.getHours();
  return hour < 5 ? "Good evening" : hour < 12 ? "Good morning" : hour < 18 ? "Good afternoon" : "Good evening";
}

/** The name to greet someone by: the first of their names. */
export function firstName(displayName: string): string {
  return displayName.trim().split(/\s+/)[0] ?? "";
}
