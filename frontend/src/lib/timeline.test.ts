import { describe, expect, it } from "vitest";
import type { Agreement } from "./customers.js";
import type { Renewal, Task } from "./planning.js";
import {
  filterTimeline, isoWeek, longDay, shortDay, timelineItems, timelineMonths, weekRange, weekStart,
  type TimelineItem, type WeekRow,
} from "./timeline.js";
import type { LogEntry } from "./worklog.js";

const NOW = "2026-11-18"; // a Wednesday, in week 47

const task = (id: number, due_on: string, extra: Partial<Task> = {}): Task => ({
  id, title: `Task ${id}`, notes: "", due_on, audience: "technicians", people: [], service_id: null, service: null,
  system_id: null, system: null, ticket: "", every: null, renewal_id: null, may_remove: true, ...extra,
});

const renewal = (id: number, renews_on: string, extra: Partial<Renewal> = {}): Renewal => ({
  id, what: `Renewal ${id}`, kind: "licence", renews_on, every: null, warn_days: 30, audience: "managers",
  people: [], who: [], service_id: null, service: null, system_id: null, system: null, supplier: "", notes: "",
  decision: "", reason: "", fallback: "", ...extra,
});

// Local times, so the test reads the same in any time zone.
const entry = (id: number, local: Date, extra: Partial<LogEntry> = {}): LogEntry => ({
  id, kind: "work", happened_at: local.toISOString(), author_id: 1, author: "Astrid Fjeld", text: `Entry ${id}`,
  service_id: null, service: null, system_ids: [], systems: [], case_number: "", coverage: "", on_site: false,
  ticket: "", may_change: true, ...extra,
});

const agreement = (extra: Partial<Agreement> = {}): Agreement => ({
  id: 1, name: "Service agreement 2026", kind: "service", status: "active", starts_on: "2026-01-01",
  ends_on: "2026-12-31", notice_by: "2026-10-01", auto_renews: true, company_id: null, notice_period: "",
  sla: "", price_section: "", notes: "", sections: [{ ref: "§ 3.1", text: "Support", service_id: 4, terms: false }],
  versions: [{ number: 1, sent_on: null, signed_on: "2025-12-15", signed_for_customer: "Signe Holm",
    signed_for_us: "", note: "" }],
  ...extra,
});

describe("weeks", () => {
  it("start on Monday and are numbered the ISO way", () => {
    expect(weekStart("2026-11-18")).toBe("2026-11-16");
    expect(weekStart("2026-11-22")).toBe("2026-11-16");
    expect(weekStart("2026-11-16")).toBe("2026-11-16");
    expect(isoWeek("2026-11-18")).toBe(47);
    expect(isoWeek("2027-01-01")).toBe(53); // a Friday: still 2026's last week
    expect(isoWeek("2027-01-04")).toBe(1);
    expect(isoWeek("2024-12-30")).toBe(1); // a Monday: already 2025's first week
  });

  it("show their dates", () => {
    expect(weekRange("2026-11-16")).toBe("16–22 Nov");
    expect(weekRange("2026-11-30")).toBe("30 Nov – 6 Dec");
    expect(shortDay("2026-11-24")).toBe("Tue 24 Nov");
    expect(longDay("2026-11-18")).toBe("Wednesday 18 November 2026");
  });
});

describe("the line's items", () => {
  it("are the tasks, renewals, agreement dates and work log, the latest first", () => {
    const items = timelineItems({
      tasks: [task(1, "2026-11-25", { every: { count: 3, unit: "months" }, service: "Updates and maintenance" }),
        task(2, "2026-11-10", { audience: "people", people: [{ id: 7, display_name: "Astrid Fjeld" }] })],
      renewals: [renewal(1, "2026-12-01", { decision: "waiting" }), renewal(2, "2026-11-01"),
        renewal(3, "2026-10-01", { decision: "declined" }), renewal(4, "2027-06-30", { decision: "renewed" })],
      agreements: [agreement()],
    }, [entry(1, new Date(2026, 10, 18, 9, 5)), entry(2, new Date(2026, 10, 12, 14, 0), { kind: "visit" })], NOW);
    expect(items.map((i) => [i.key, i.type, i.state, i.day])).toEqual([
      ["renewal-4", "renewal", "done", "2027-06-30"],
      ["agreement-1-ends", "agreement", "coming", "2026-12-31"],
      ["renewal-1", "renewal", "coming", "2026-12-01"],
      ["task-1", "recurring", "coming", "2026-11-25"],
      ["log-1", "work", "done", "2026-11-18"],
      ["log-2", "visit", "done", "2026-11-12"],
      ["task-2", "task", "overdue", "2026-11-10"],
      ["renewal-2", "renewal", "overdue", "2026-11-01"],
      ["agreement-1-notice", "agreement", "done", "2026-10-01"],
      ["renewal-3", "renewal", "done", "2026-10-01"],
      ["agreement-1-signed", "agreement", "done", "2025-12-15"],
    ]);
    const found = (key: string) => items.find((i) => i.key === key)!;
    expect(found("task-1").detail).toBe("Every 3 months · Updates and maintenance · For the customer's technicians");
    expect(found("task-2").detail).toBe("For Astrid Fjeld");
    expect(found("agreement-1-ends").title).toBe("Service agreement 2026 renews by itself");
    expect(found("agreement-1-signed").detail).toBe("Version 1 · by Signe Holm");
    expect(found("log-1").time).toBe("09:05");
  });

  it("leave out an offer's dates and show an ended agreement's end", () => {
    const dates = (extra: Partial<Agreement>) =>
      timelineItems({ tasks: [], renewals: [], agreements: [agreement(extra)] }, [], NOW).map((i) => i.title);
    expect(dates({ status: "offer" })).toEqual([]);
    expect(dates({ status: "ended", ends_on: "2026-06-30", versions: [] })).toEqual(["Service agreement 2026 ended"]);
    expect(dates({ starts_on: "2027-01-01", ends_on: null, notice_by: null, versions: [] })).toEqual([
      "Service agreement 2026 starts"]);
  });

  it("are narrowed by service, system and type", () => {
    const items = timelineItems({
      tasks: [task(1, "2026-11-25", { service_id: 4 }), task(2, "2026-11-26", { system_id: 9 })],
      renewals: [renewal(1, "2026-12-01", { service_id: 4, system_id: 9 })], agreements: [agreement()],
    }, [entry(1, new Date(2026, 10, 17, 9, 0), { system_ids: [9, 3] })], NOW);
    const keys = (filter: Parameters<typeof filterTimeline>[1]) => filterTimeline(items, filter).map((i) => i.key);
    expect(keys({ service_id: 4, system_id: null, hidden: [] })).toEqual([
      "agreement-1-ends", "renewal-1", "task-1", "agreement-1-notice", "agreement-1-signed"]);
    expect(keys({ service_id: null, system_id: 9, hidden: [] })).toEqual(["renewal-1", "task-2", "log-1"]);
    expect(keys({ service_id: null, system_id: null, hidden: ["agreement", "task", "log"] })).toEqual(["renewal-1"]);
  });
});

describe("the line by month and week", () => {
  const item = (key: string, day: string, at = `${day}T99:99`): TimelineItem => ({
    key, type: "task", state: "coming", day, at, time: null, title: key, detail: "", service_ids: [], system_ids: [],
  });
  const shape = (items: TimelineItem[], everyWeek = false) =>
    timelineMonths(items, NOW, everyWeek).map((month) => [month.label, month.rows.map((row) =>
      row.kind === "gap" ? `${row.weeks} ${row.future ? "planned" : "logged"}`
        : `W ${row.week}: ${row.items.map((i) => (i === "today" ? "today" : i.key)).join(", ") || "empty"}`)]);

  it("has today's row even with nothing on it", () => {
    expect(shape([])).toEqual([["November 2026", ["W 47: today"]]]);
  });

  it("puts what's due today above today's row, and what was done today below", () => {
    const items = [item("due-today", NOW), item("done-today", NOW, `${NOW}T08:30`), item("monday", "2026-11-16"),
      item("friday", "2026-11-20")].sort((a, b) => (a.at < b.at ? 1 : -1));
    expect(shape(items)).toEqual([["November 2026", ["W 47: friday, due-today, today, done-today, monday"]]]);
  });

  it("folds empty weeks into one line, under the month above them", () => {
    const items = [item("far", "2027-01-06"), item("next", "2026-11-24"), item("old", "2026-10-13")];
    expect(shape(items)).toEqual([
      ["January 2027", ["W 1: far", "W 49–53 planned"]],
      ["November 2026", ["W 48: next", "W 47: today", "W 43–46 logged"]],
      ["October 2026", ["W 42: old"]],
    ]);
  });

  it("shows every week when asked", () => {
    const rows = shape([item("next", "2026-12-02"), item("old", "2026-11-03")], true);
    expect(rows).toEqual([
      ["December 2026", ["W 49: next"]],
      ["November 2026", ["W 48: empty", "W 47: today", "W 46: empty", "W 45: old"]],
    ]);
    const week = timelineMonths([item("next", "2026-12-02")], NOW, true)[1].rows[0] as WeekRow;
    expect([week.future, week.range]).toEqual([true, "23–29 Nov"]);
  });
});
