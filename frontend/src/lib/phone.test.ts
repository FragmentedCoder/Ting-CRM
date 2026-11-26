import { describe, expect, it } from "vitest";
import { codeChoices, joinPhone, splitPhone } from "./phone.js";

describe("a phone number", () => {
  it("comes apart into its country code and the rest, as written", () => {
    expect(splitPhone("+45 12 34 56 78", "+45")).toEqual({ code: "+45", number: "12 34 56 78" });
    expect(splitPhone("+4512345678", "+45")).toEqual({ code: "+45", number: "12345678" });
    expect(splitPhone("0046 8 123 456", "+45")).toEqual({ code: "+46", number: "8 123 456" });
    expect(splitPhone("+358 40 123 4567", "+45")).toEqual({ code: "+358", number: "40 123 4567" });
    expect(splitPhone("+1 (555) 010-9999", "+45")).toEqual({ code: "+1", number: "(555) 010-9999" });
  });

  it("starts on the team's own code when empty, and keeps none when written without one", () => {
    expect(splitPhone("", "+46")).toEqual({ code: "+46", number: "" });
    expect(splitPhone("12 34 56 78", "+45")).toEqual({ code: "", number: "12 34 56 78" });
    // A code Þing doesn't list stays in the number.
    expect(splitPhone("+999 123", "+45")).toEqual({ code: "", number: "+999 123" });
    // The team's own code is known even when it isn't on the list.
    expect(splitPhone("+423 123 45 67", "+423")).toEqual({ code: "+423", number: "123 45 67" });
  });

  it("goes back together as one line", () => {
    expect(joinPhone("+45", " 12 34 56 78 ")).toBe("+45 12 34 56 78");
    expect(joinPhone("+45", "")).toBe("");
    expect(joinPhone("", "12 34 56 78")).toBe("12 34 56 78");
    // A number typed with its own code keeps it.
    expect(joinPhone("+45", "+46 8 123 456")).toBe("+46 8 123 456");
  });

  it("offers the team's code first, and one that isn't listed by its digits", () => {
    expect(codeChoices("+46").slice(0, 2).map((c) => c.code)).toEqual(["+46", "+45"]);
    expect(codeChoices("+423")[0]).toEqual({ code: "+423", name: "" });
    expect(codeChoices("+45", "+47").slice(0, 2).map((c) => c.code)).toEqual(["+45", "+47"]);
    expect(codeChoices("+45").filter((c) => c.code === "+45")).toHaveLength(1);
  });
});
