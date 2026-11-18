import { describe, expect, it } from "vitest";
import {
  addDays, addInterval, daysBetween, decisionPill, dueTone, dueWords, forWhom, renewalOpen, rhythm, today,
  warnLine,
} from "./planning.js";

describe("dates", () => {
  it("count an interval on, keeping to the month's end", () => {
    expect(addInterval("2026-08-20", { count: 3, unit: "months" })).toBe("2026-11-20");
    expect(addInterval("2026-01-31", { count: 1, unit: "months" })).toBe("2026-02-28");
    expect(addInterval("2026-11-30", { count: 3, unit: "months" })).toBe("2027-02-28");
    expect(addInterval("2026-10-27", { count: 2, unit: "weeks" })).toBe("2026-11-10");
  });

  it("count days across a month and a change of clocks", () => {
    expect(addDays("2026-10-24", 2)).toBe("2026-10-26");
    expect(addDays("2026-12-01", -2)).toBe("2026-11-29");
    expect(daysBetween("2026-11-18", "2026-12-01")).toBe(13);
  });

  it("give today as the viewer's own day", () => {
    expect(today(new Date(2026, 10, 18, 0, 30))).toBe("2026-11-18");
    expect(today(new Date(2026, 10, 18, 23, 30))).toBe("2026-11-18");
  });
});

describe("a rhythm", () => {
  it("is said the way people say it", () => {
    expect(rhythm({ count: 1, unit: "weeks" })).toBe("Every week");
    expect(rhythm({ count: 3, unit: "months" })).toBe("Every 3 months");
    expect(rhythm({ count: 12, unit: "months" })).toBe("Every year");
    expect(rhythm({ count: 36, unit: "months" })).toBe("Every 3 years");
  });
});

describe("a due date", () => {
  it("is red when passed and yellow within a week", () => {
    expect(dueTone("2026-11-17", "2026-11-18")).toBe("critical");
    expect(dueTone("2026-11-25", "2026-11-18")).toBe("warning");
    expect(dueTone("2026-11-26", "2026-11-18")).toBe("neutral");
  });

  it("says how far off it is", () => {
    expect(dueWords("2026-11-15", "2026-11-18")).toBe("Overdue by 3 days");
    expect(dueWords("2026-11-17", "2026-11-18")).toBe("Overdue by 1 day");
    expect(dueWords("2026-11-18", "2026-11-18")).toBe("Today");
    expect(dueWords("2026-11-19", "2026-11-18")).toBe("Tomorrow");
    expect(dueWords("2026-11-30", "2026-11-18")).toBe("In 12 days");
  });
});

describe("a renewal", () => {
  it("shows its decision in the fixed words", () => {
    const on = (decision: "" | "approved" | "waiting" | "renewed" | "declined", renews_on = "2026-12-01") =>
      decisionPill({ decision, renews_on }, "2026-11-18");
    expect(on("approved")).toEqual({ tone: "ok", text: "Approved" });
    expect(on("waiting")).toEqual({ tone: "warning", text: "Waiting for the customer" });
    expect(on("renewed")).toEqual({ tone: "ok", text: "Renewed" });
    expect(on("declined")).toEqual({ tone: "critical", text: "Won't be renewed" });
    expect(on("")).toEqual({ tone: "warning", text: "Renewal open" });
    expect(on("", "2026-11-01")).toEqual({ tone: "critical", text: "Overdue, no decision" });
  });

  it("is open until it's renewed, or has run out as decided", () => {
    expect(renewalOpen({ decision: "", renews_on: "2026-11-01" }, "2026-11-18")).toBe(true);
    expect(renewalOpen({ decision: "declined", renews_on: "2026-12-01" }, "2026-11-18")).toBe(true);
    expect(renewalOpen({ decision: "declined", renews_on: "2026-11-01" }, "2026-11-18")).toBe(false);
    expect(renewalOpen({ decision: "renewed", renews_on: "2026-12-01" }, "2026-11-18")).toBe(false);
  });

  it("says whom it warns, and how early", () => {
    expect(warnLine({ warn_days: 30, audience: "managers", who: [] })).toBe("Warns the Managers 30 days before");
    expect(warnLine({ warn_days: 1, audience: "technicians", who: [] })).toBe(
      "Warns the customer's technicians 1 day before");
    expect(warnLine({ warn_days: 0, audience: "people", who: [{ id: 1, display_name: "Astrid Fjeld" }] })).toBe(
      "Warns Astrid Fjeld on the day");
    expect(forWhom("people", [])).toBe("Nobody");
  });
});
