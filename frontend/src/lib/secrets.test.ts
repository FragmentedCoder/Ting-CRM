import { describe, expect, it } from "vitest";
import { recoveryCodesText, recoveryCodesWording } from "./secrets";

describe("recovery codes", () => {
  it("speak of ten one-time codes for most people", () => {
    const text = recoveryCodesText("astrid", ["aaaa-bbbb-cccc", "dddd-eeee-ffff"]);
    expect(text).toContain("Each code lets you sign in once");
    expect(recoveryCodesWording(false).heading).toBe("Save your recovery codes");
  });

  it("speak of one code good every time for the break-glass Administrator", () => {
    const text = recoveryCodesText("ingrid", ["aaaa-bbbb-cccc-dddd-eeee-ffff"], true);
    expect(text).toContain("the break-glass Administrator");
    expect(text).toContain("as often as you need");
    expect(text).toContain("sudo ting admin recovery-code");
    expect(text).toContain("aaaa-bbbb-cccc-dddd-eeee-ffff");
    const wording = recoveryCodesWording(true);
    expect(wording.heading).toBe("Save your recovery code");
    expect(wording.confirmation).toBe("I have saved this code somewhere safe");
  });
});
