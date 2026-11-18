// A customer's timeline: what's coming up (tasks, recurring work, renewals, agreement
// dates) and what was done (the work log) merged into one line, the future above
// today and the past below, by month and week.

import { currentVersion, type Agreement, type CustomerDetail } from "./customers.js";
import { addDays, forWhom, renewalOpen, rhythm, type Renewal, type Task } from "./planning.js";
import { type LogEntry, type LogKind } from "./worklog.js";

export type TimelineType = "task" | "recurring" | "renewal" | "agreement" | LogKind;
/** Coming up (an open ring), overdue (red) or done (grey). */
export type TimelineState = "coming" | "overdue" | "done";

export const TIMELINE_TYPES: Record<TimelineType, string> = {
  task: "Task",
  recurring: "Recurring",
  renewal: "Renewal",
  agreement: "Agreement",
  call: "Call",
  work: "Work log",
  visit: "Visit",
  meeting: "Meeting",
  email: "Email",
  document: "Document",
};

/** What "Show by type" offers; the work log's kinds go together. */
export type TypeGroup = "task" | "recurring" | "renewal" | "agreement" | "log";
export const TYPE_GROUPS: Record<TypeGroup, string> = {
  task: "Tasks",
  recurring: "Recurring work",
  renewal: "Renewals",
  agreement: "Agreement dates",
  log: "Work log",
};

export function typeGroup(type: TimelineType): TypeGroup {
  return type === "task" || type === "recurring" || type === "renewal" || type === "agreement" ? type : "log";
}

export interface TimelineItem {
  key: string;
  type: TimelineType;
  state: TimelineState;
  /** The day it's on, in the viewer's time zone: "2026-11-18". */
  day: string;
  /** Orders the line: within a day, what's planned sits above what was done. */
  at: string;
  /** The time of day, for what was logged. */
  time: string | null;
  title: string;
  /** Under the title: the service, the system, who it's for. */
  detail: string;
  service_ids: number[];
  system_ids: number[];
  task?: Task;
  renewal?: Renewal;
  entry?: LogEntry;
  agreement?: Agreement;
}

const PLANNED = "T99:99";
/** Today's row: below what's due today, above what was done today. */
const TODAY = "T99:00";

function localStamp(iso: string): string {
  const moment = new Date(iso);
  return new Date(moment.getTime() - moment.getTimezoneOffset() * 60_000).toISOString().slice(0, 16);
}

function joined(...parts: (string | null | undefined | false)[]): string {
  return parts.filter(Boolean).join(" · ");
}

function agreementItems(agreement: Agreement, now: string): TimelineItem[] {
  if (agreement.status === "offer") return [];
  const services = [...new Set(agreement.sections.map((s) => s.service_id).filter((s) => s !== null))];
  const dated = (suffix: string, day: string | null | undefined, title: string, detail = ""): TimelineItem[] =>
    day ? [{
      key: `agreement-${agreement.id}-${suffix}`, type: "agreement", state: day >= now ? "coming" : "done", day,
      at: day + PLANNED, time: null, title, detail, service_ids: services, system_ids: [], agreement,
    }] : [];
  const signed = currentVersion(agreement);
  const active = agreement.status === "active";
  return [
    ...dated("signed", signed?.signed_on, `${agreement.name} signed`,
      joined(signed && `Version ${signed.number}`, signed?.signed_for_customer && `by ${signed.signed_for_customer}`)),
    ...(active && agreement.starts_on && agreement.starts_on > now
      ? dated("starts", agreement.starts_on, `${agreement.name} starts`) : []),
    ...(active ? dated("notice", agreement.notice_by, `Last day to give notice on ${agreement.name}`,
      agreement.auto_renews ? "After this it renews by itself" : "") : []),
    ...dated("ends", agreement.ends_on,
      active ? `${agreement.name} ${agreement.auto_renews ? "renews by itself" : "ends"}` : `${agreement.name} ended`),
  ];
}

/** Everything on the customer's line, the latest first. */
export function timelineItems(
  customer: Pick<CustomerDetail, "tasks" | "renewals" | "agreements">, entries: LogEntry[], now: string,
): TimelineItem[] {
  const tasks = (customer.tasks ?? []).map((task): TimelineItem => ({
    key: `task-${task.id}`, type: task.every ? "recurring" : "task",
    state: task.due_on < now ? "overdue" : "coming", day: task.due_on, at: task.due_on + PLANNED, time: null,
    title: task.title,
    detail: joined(task.every && rhythm(task.every), task.service, task.system,
      `For ${forWhom(task.audience, task.people).replace(/^The /, "the ")}`, task.ticket && `Ticket ID ${task.ticket}`),
    service_ids: task.service_id === null ? [] : [task.service_id],
    system_ids: task.system_id === null ? [] : [task.system_id], task,
  }));
  const renewals = (customer.renewals ?? []).map((renewal): TimelineItem => ({
    key: `renewal-${renewal.id}`, type: "renewal",
    state: !renewalOpen(renewal, now) ? "done" : renewal.renews_on < now ? "overdue" : "coming",
    day: renewal.renews_on, at: renewal.renews_on + PLANNED, time: null, title: renewal.what,
    detail: joined(renewal.every && rhythm(renewal.every), renewal.service, renewal.system, renewal.supplier),
    service_ids: renewal.service_id === null ? [] : [renewal.service_id],
    system_ids: renewal.system_id === null ? [] : [renewal.system_id], renewal,
  }));
  const agreements = (customer.agreements ?? []).flatMap((agreement) => agreementItems(agreement, now));
  const logged = entries.map((entry): TimelineItem => {
    const at = localStamp(entry.happened_at);
    return {
      key: `log-${entry.id}`, type: entry.kind, state: "done", day: at.slice(0, 10), at, time: at.slice(11),
      title: entry.text,
      detail: joined(entry.author, entry.service, entry.systems.join(", "), entry.case_number,
        entry.on_site && "On site", entry.ticket && `Ticket ID ${entry.ticket}`),
      service_ids: entry.service_id === null ? [] : [entry.service_id], system_ids: entry.system_ids, entry,
    };
  });
  return [...tasks, ...renewals, ...agreements, ...logged]
    .sort((a, b) => (a.at < b.at ? 1 : a.at > b.at ? -1 : a.key.localeCompare(b.key)));
}

export interface TimelineFilter {
  service_id: number | null;
  system_id: number | null;
  /** The type groups left out. */
  hidden: TypeGroup[];
}

export function filterTimeline(items: TimelineItem[], filter: TimelineFilter): TimelineItem[] {
  return items.filter((item) =>
    !filter.hidden.includes(typeGroup(item.type))
    && (filter.service_id === null || item.service_ids.includes(filter.service_id))
    && (filter.system_id === null || item.system_ids.includes(filter.system_id)));
}

/** The Monday of a day's week. */
export function weekStart(day: string): string {
  const weekday = (new Date(day).getUTCDay() + 6) % 7;
  return addDays(day, -weekday);
}

/** The ISO 8601 week number: the week with the year's first Thursday is week 1. */
export function isoWeek(day: string): number {
  const thursday = addDays(weekStart(day), 3);
  const firstDay = `${thursday.slice(0, 4)}-01-01`;
  return Math.floor((Date.parse(thursday) - Date.parse(firstDay)) / (7 * 86_400_000)) + 1;
}

const DAY_MONTH = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", timeZone: "UTC" });
const MONTH_YEAR = new Intl.DateTimeFormat("en-GB", { month: "long", year: "numeric", timeZone: "UTC" });
const WEEKDAY = new Intl.DateTimeFormat("en-GB", { weekday: "short", day: "numeric", month: "short", timeZone: "UTC" });
const LONG_DAY = new Intl.DateTimeFormat("en-GB", {
  weekday: "long", day: "numeric", month: "long", year: "numeric", timeZone: "UTC",
});

/** "16–22 Nov", or "30 Nov – 6 Dec" across a month's end. */
export function weekRange(monday: string): string {
  const sunday = addDays(monday, 6);
  return monday.slice(0, 7) === sunday.slice(0, 7)
    ? `${Number(monday.slice(8))}–${DAY_MONTH.format(new Date(sunday))}`
    : `${DAY_MONTH.format(new Date(monday))} – ${DAY_MONTH.format(new Date(sunday))}`;
}

/** "Tue 24 Nov". */
export function shortDay(day: string): string {
  return WEEKDAY.format(new Date(day)).replace(",", "");
}

/** "Wednesday 18 November 2026". */
export function longDay(day: string): string {
  return LONG_DAY.format(new Date(day)).replace(",", "");
}

export interface WeekRow {
  kind: "week";
  key: string;
  week: number;
  range: string;
  /** Later than this week, for "Nothing planned" rather than "Nothing logged". */
  future: boolean;
  /** The week's items, the latest first, with today's row where it falls. */
  items: (TimelineItem | "today")[];
}

/** Weeks with nothing in them, folded into one line. */
export interface GapRow {
  kind: "gap";
  key: string;
  /** "W 50–52", "W 50" for one week, or "W 51 2026 – W 6 2027" across a new year. */
  weeks: string;
  future: boolean;
}

export interface MonthBlock {
  key: string;
  /** "November 2026" */
  label: string;
  rows: (WeekRow | GapRow)[];
}

/** The line by month and week, the latest first. Today's week is always there;
 *  empty weeks fold into one line unless every week is asked for. A week belongs to
 *  the month its Thursday is in. */
export function timelineMonths(items: TimelineItem[], now: string, everyWeek = false): MonthBlock[] {
  const thisWeek = weekStart(now);
  const byWeek = new Map<string, TimelineItem[]>();
  for (const item of items) {
    const monday = weekStart(item.day);
    byWeek.set(monday, [...(byWeek.get(monday) ?? []), item]);
  }
  const mondays = [...byWeek.keys(), thisWeek].sort();
  const months: MonthBlock[] = [];
  const place = (monday: string, row: WeekRow | GapRow, own: boolean) => {
    const month = addDays(monday, 3).slice(0, 7);
    if (own && months.at(-1)?.key !== month) {
      months.push({ key: month, label: MONTH_YEAR.format(new Date(`${month}-01`)), rows: [] });
    }
    months.at(-1)?.rows.push(row);
  };
  let empty: string[] = [];
  const fold = () => {
    if (!empty.length) return;
    const [latest, earliest] = [empty[0], empty.at(-1)!];
    // The weeks' years, when the run crosses a new year: "W 51 2026 – W 6 2027".
    const [from, to] = [addDays(earliest, 3).slice(0, 4), addDays(latest, 3).slice(0, 4)];
    const weeks = latest === earliest ? `W ${isoWeek(latest)}`
      : from === to ? `W ${isoWeek(earliest)}–${isoWeek(latest)}`
        : `W ${isoWeek(earliest)} ${from} – W ${isoWeek(latest)} ${to}`;
    // A folded run sits under the month above it.
    place(latest, { kind: "gap", key: `gap-${latest}`, weeks, future: latest > thisWeek }, false);
    empty = [];
  };
  for (let monday = mondays.at(-1)!; monday >= mondays[0]; monday = addDays(monday, -7)) {
    const found = byWeek.get(monday) ?? [];
    if (!found.length && monday !== thisWeek && !everyWeek) {
      empty.push(monday);
      continue;
    }
    fold();
    const rows: (TimelineItem | "today")[] = [...found];
    if (monday === thisWeek) {
      const below = rows.findIndex((item) => item !== "today" && item.at < now + TODAY);
      rows.splice(below === -1 ? rows.length : below, 0, "today");
    }
    place(monday, {
      kind: "week", key: `week-${monday}`, week: isoWeek(monday), range: weekRange(monday),
      future: monday > thisWeek, items: rows,
    }, true);
  }
  return months;
}
