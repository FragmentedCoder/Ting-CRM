import { describe, expect, it } from "vitest";
import { ACCENT, customSwatch, effectiveColours, PRIMARY } from "./colours";

// Þing's surfaces (docs/brand/tokens.json): page, card and subtle backgrounds.
const LIGHT = ["#FFFFFF", "#F7F7F7", "#EFEFEF"];
const DARK = ["#0B1420", "#13202F", "#1B2B3D"];

function luminance(hex: string): number {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255);
  const linear = (c: number) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
  return 0.2126 * linear(r) + 0.7152 * linear(g) + 0.0722 * linear(b);
}

function contrast(a: string, b: string): number {
  const [high, low] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (high + 0.05) / (low + 0.05);
}

describe("primary colours", () => {
  it.each(PRIMARY)("$name reads as link text and carries button text, light and dark", (swatch) => {
    for (const surface of LIGHT) expect(contrast(swatch.light, surface)).toBeGreaterThanOrEqual(4.5);
    for (const surface of DARK) expect(contrast(swatch.dark, surface)).toBeGreaterThanOrEqual(4.5);
    expect(contrast("#FFFFFF", swatch.light)).toBeGreaterThanOrEqual(4.5);
    expect(contrast("#0B1420", swatch.dark)).toBeGreaterThanOrEqual(4.5);
  });
});

describe("accent colours", () => {
  // Accents mark things (the current page, a command) and never carry text: 3:1.
  it.each(ACCENT)("$name stands out from the card, light and dark", (swatch) => {
    expect(contrast(swatch.light, "#FFFFFF")).toBeGreaterThanOrEqual(3);
    expect(contrast(swatch.dark, "#13202F")).toBeGreaterThanOrEqual(3);
  });
});

describe("custom colours", () => {
  // Hard cases (pure yellow, navy, white, black, mid grey) and an even spread of hues.
  const picks = ["#FFFF00", "#000080", "#FFFFFF", "#000000", "#777777", "#FF8800", "#00FF00"];
  for (let i = 0; i < 60; i++) {
    const channel = (n: number) => ((i * n * 37) % 256).toString(16).padStart(2, "0");
    picks.push(`#${channel(3)}${channel(5)}${channel(7)}`.toUpperCase());
  }

  it.each(picks)("%s as a primary stays readable in light and dark mode", (pick) => {
    const swatch = customSwatch(pick, "primary");
    for (const surface of LIGHT) expect(contrast(swatch.light, surface)).toBeGreaterThanOrEqual(4.5);
    for (const surface of DARK) expect(contrast(swatch.dark, surface)).toBeGreaterThanOrEqual(4.5);
    expect(contrast("#FFFFFF", swatch.light)).toBeGreaterThanOrEqual(4.5);
    expect(contrast("#0B1420", swatch.dark)).toBeGreaterThanOrEqual(4.5);
  });

  it.each(picks)("%s as an accent stands out in light and dark mode", (pick) => {
    const swatch = customSwatch(pick, "accent");
    expect(contrast(swatch.light, "#FFFFFF")).toBeGreaterThanOrEqual(3);
    expect(contrast(swatch.dark, "#13202F")).toBeGreaterThanOrEqual(3);
  });

  it("keeps a colour that already passes, and changes one that doesn't only as needed", () => {
    expect(customSwatch("#2b5d8a", "primary").light).toBe("#2B5D8A");
    const yellow = customSwatch("#FFFF00", "primary").light;
    expect(yellow).not.toBe("#FFFF00");
    expect(contrast(yellow, "#EFEFEF")).toBeLessThan(5); // just past 4.5, not black
  });
});

describe("effectiveColours", () => {
  const site = { primary_colour: "pine", accent_colour: "sky", enforce_colours: false };

  it("uses the person's own, falling back to the site's", () => {
    expect(effectiveColours(site, { primary: "rose", accent: null })).toEqual({
      primary: "rose",
      accent: "sky",
    });
  });

  it("uses the site's when an administrator enforces them", () => {
    expect(
      effectiveColours({ ...site, enforce_colours: true }, { primary: "rose", accent: "moss" }),
    ).toEqual({ primary: "pine", accent: "sky" });
  });
});
