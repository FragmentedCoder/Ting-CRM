import { describe, expect, it } from "vitest";
import { byDay, initials, toLocalInput, type LogEntry } from "./worklog.js";

const entry = (id: number, happened_at: string): LogEntry => ({
  id, kind: "work", happened_at, author_id: 1, author: "Astrid Fjeld", text: "x", service_id: null,
  service: null, system_ids: [], systems: [], case_number: "", coverage: "", on_site: false,
  ticket: "", may_change: true,
});

describe("byDay", () => {
  it("groups entries under their day, keeping their order", () => {
    const days = byDay([entry(3, "2026-10-27T12:00:00Z"), entry(2, "2026-10-27T09:00:00Z"), entry(1, "2026-10-02T12:00:00Z")]);
    expect(days.map((d) => d.entries.map((e) => e.id))).toEqual([[3, 2], [1]]);
    expect(days[0].day).toContain("27 October 2026");
  });
});

describe("initials", () => {
  it("takes the first and last name's letters", () => {
    expect(initials("Astrid Fjeld")).toBe("AF");
    expect(initials("Mikkel van der Lund")).toBe("ML");
    expect(initials("Mona")).toBe("M");
    expect(initials(null)).toBe("?");
  });
});

describe("toLocalInput", () => {
  it("gives local time to the minute, as a datetime-local input takes it", () => {
    const moment = new Date(2026, 9, 27, 14, 5, 30);
    expect(toLocalInput(moment)).toBe("2026-10-27T14:05");
  });
});
