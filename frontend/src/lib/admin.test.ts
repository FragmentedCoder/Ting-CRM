import { describe, expect, it } from "vitest";
import { newPasswordChoice, passwordFields, userStatus, type UserSummary } from "./admin";
import { bytes, since } from "./format";

describe("passwordFields", () => {
  it("sends nothing for Þing's random password", () => {
    expect(passwordFields(newPasswordChoice())).toEqual({});
  });

  it("sends a chosen password, temporary unless unticked", () => {
    const choice = { mode: "chosen" as const, password: "a long one", repeat: "a long one", mustChange: false };
    expect(passwordFields(choice)).toEqual({ password: "a long one", must_change_password: false });
  });

  it("refuses two passwords that differ", () => {
    const choice = { mode: "chosen" as const, password: "one", repeat: "two", mustChange: true };
    expect(passwordFields(choice)).toBe("The two passwords don't match.");
  });
});

describe("userStatus", () => {
  const base = {
    is_active: true, locked: false, password_change_required: false, second_factors: 0,
    mfa_required: true,
  } as UserSummary;

  it("shows a disabled account in red", () => {
    expect(userStatus({ ...base, is_active: false })).toEqual({ tone: "critical", text: "Disabled" });
  });

  it("flags missing multifactor only when it's required", () => {
    expect(userStatus(base).text).toBe("Multifactor not set up");
    expect(userStatus({ ...base, mfa_required: false }).text).toBe("Active");
  });
});

describe("format", () => {
  it.each([
    [512, "512 bytes"],
    [2048, "2.0 KB"],
    [5 * 1024 ** 3, "5.0 GB"],
  ])("bytes(%i) is %s", (size, text) => {
    expect(bytes(size)).toBe(text);
  });

  it("says how long ago, roughly", () => {
    const now = Date.parse("2026-10-24T12:00:00Z");
    expect(since("2026-10-24T11:58:00Z", now)).toBe("2 minutes");
    expect(since("2026-10-21T08:00:00Z", now)).toBe("3 days, 4 hours");
  });
});
