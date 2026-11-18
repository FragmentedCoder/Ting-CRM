import { describe, expect, it } from "vitest";
import { firstName, greeting, reasonWords, type Reason } from "./mywork.js";

const NOW = "2026-11-18";
const reason = (kind: Reason["kind"], extra: Partial<Reason> = {}): Reason => ({
  kind, tone: "warning", count: 1, what: "", day: null, ...extra,
});

describe("why a customer needs attention", () => {
  it("names the one thing, or counts several", () => {
    expect(reasonWords(reason("tasks_overdue"), NOW)).toBe("1 task overdue");
    expect(reasonWords(reason("tasks_overdue", { count: 3 }), NOW)).toBe("3 tasks overdue");
    expect(reasonWords(reason("renewal_overdue", { what: "Firewall feature key" }), NOW)).toBe(
      "Renewal overdue: Firewall feature key");
    expect(reasonWords(reason("renewal_overdue", { count: 2, what: "Firewall feature key" }), NOW)).toBe(
      "2 renewals overdue");
    expect(reasonWords(reason("renewal_soon", { what: "Antivirus", day: "2026-11-30" }), NOW)).toBe(
      "Renewal in 12 days: Antivirus");
    expect(reasonWords(reason("renewal_soon", { what: "Antivirus", day: "2026-11-19" }), NOW)).toBe(
      "Renewal tomorrow: Antivirus");
    expect(reasonWords(reason("renewal_soon", { what: "Antivirus", day: NOW }), NOW)).toBe("Renewal today: Antivirus");
    expect(reasonWords(reason("renewal_soon", { count: 4 }), NOW)).toBe("4 renewals within 30 days");
    expect(reasonWords(reason("notice", { what: "Service agreement 2026", day: "2026-12-28" }), NOW)).toBe(
      "Notice by 28 Dec 2026: Service agreement 2026");
    expect(reasonWords(reason("uncovered", { what: "Backup" }), NOW)).toBe("No agreement: Backup");
    expect(reasonWords(reason("uncovered", { count: 2, what: "Backup" }), NOW)).toBe("2 services without agreement");
  });
});

describe("the greeting", () => {
  it("follows the viewer's clock", () => {
    const at = (hour: number) => greeting(new Date(2026, 10, 18, hour, 30));
    expect([at(2), at(7), at(12), at(17), at(18), at(23)]).toEqual([
      "Good evening", "Good morning", "Good afternoon", "Good afternoon", "Good evening", "Good evening"]);
  });

  it("uses the first name", () => {
    expect(firstName("Astrid Fjeld")).toBe("Astrid");
    expect(firstName("  Tor  ")).toBe("Tor");
    expect(firstName("")).toBe("");
  });
});
