import { encode } from "uqr";
import { describe, expect, it } from "vitest";
import { groupSecret, qrPath, QUIET_ZONE } from "./qr";

describe("qrPath", () => {
  it("draws one square per dark module, inside a quiet zone", () => {
    const text = "otpauth://totp/%C3%9Eing:astrid?secret=JBSWY3DPEHPK3PXP&issuer=%C3%9Eing";
    const { data, size } = encode(text, { ecc: "M", border: 0 });
    const qr = qrPath(text);

    expect(qr.size).toBe(size + 2 * QUIET_ZONE);
    expect(qr.d.match(/M/g)?.length).toBe(data.flat().filter(Boolean).length);
    expect(qr.d.startsWith(`M${QUIET_ZONE} ${QUIET_ZONE}`)).toBe(true); // finder pattern corner
  });
});

describe("groupSecret", () => {
  it("splits the key into groups of four", () => {
    expect(groupSecret("JBSWY3DPEHPK3PXPAB")).toBe("JBSW Y3DP EHPK 3PXP AB");
  });
});
