import { describe, expect, it } from "vitest";
import { aheadUntil, aheadWords } from "./general.svelte.js";

describe("how far ahead the team looks", () => {
  it("is a year unless set, counted in months from today", () => {
    expect(aheadUntil("2026-11-26")).toBe("2027-11-26");
    expect(aheadUntil("2026-11-26", 3)).toBe("2027-02-26");
    expect(aheadUntil("2026-11-30", 3)).toBe("2027-02-28");
    expect(aheadUntil("2026-11-26", 36)).toBe("2029-11-26");
  });

  it("reads as the next so long", () => {
    expect([3, 6, 12, 18, 24, 36].map((months) => aheadWords(months))).toEqual(
      ["3 months", "6 months", "year", "18 months", "2 years", "3 years"]);
  });
});
