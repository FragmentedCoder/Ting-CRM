// The colours people and Administrators can pick: a primary (links, focus rings,
// switches, primary buttons) and an accent (the marker on the current page in
// menus, highlighted commands). Each has a light-mode and a dark-mode value, and
// colours.test.ts checks every one for contrast (WCAG AA) on Þing's surfaces.
// The names must match backend/app/colours.py; a test checks that too.
// Administrators may also pick any colour for the site; customSwatch() then
// finds the nearest shades of it that pass the same checks.

export interface Swatch {
  key: string;
  name: string;
  light: string;
  dark: string;
}

export const PRIMARY: Swatch[] = [
  { key: "fjord", name: "Fjord", light: "#2B5D8A", dark: "#5B9BD5" },
  { key: "pine", name: "Pine", light: "#2F6B47", dark: "#5FBF84" },
  { key: "teal", name: "Teal", light: "#1D6B73", dark: "#4FBFC9" },
  { key: "plum", name: "Plum", light: "#6A4C9C", dark: "#B49DE0" },
  { key: "rose", name: "Rose", light: "#A23A64", dark: "#EE93B7" },
  { key: "slate", name: "Slate", light: "#4A5568", dark: "#AAB4C3" },
];

export const ACCENT: Swatch[] = [
  { key: "lyng", name: "Lyng", light: "#9A78B0", dark: "#B898C8" },
  { key: "copper", name: "Copper", light: "#B5652B", dark: "#E39A62" },
  { key: "moss", name: "Moss", light: "#6B8E23", dark: "#A5C85A" },
  { key: "sky", name: "Sky", light: "#2E86C1", dark: "#6DB6E8" },
  { key: "rose", name: "Rose", light: "#C2416B", dark: "#EC8AAA" },
  { key: "violet", name: "Violet", light: "#7E57C2", dark: "#B39DDB" },
];

export const DEFAULT_PRIMARY = "fjord";
export const DEFAULT_ACCENT = "lyng";

// Text on a primary button: white on the light-mode colour, near-black on the dark.
const ON_PRIMARY = { light: "#FFFFFF", dark: "#0B1420" };
// With Þing's own primary, buttons stay ink and snow (docs/brand).
const INK_BUTTON = {
  light: { bg: "#0F1B2D", text: "#FFFFFF" },
  dark: { bg: "#E8ECF0", text: "#0B1420" },
};

// Þing's surfaces (docs/brand/tokens.json): page, card and subtle backgrounds.
export const SURFACES = {
  light: ["#FFFFFF", "#F7F7F7", "#EFEFEF"],
  dark: ["#0B1420", "#13202F", "#1B2B3D"],
};
// WCAG AA: 4.5:1 for text (links, button labels), 3:1 for marks that carry no text.
const NEEDS = { primary: 4.5, accent: 3 };

function luminance(hex: string): number {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255);
  const linear = (c: number) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
  return 0.2126 * linear(r) + 0.7152 * linear(g) + 0.0722 * linear(b);
}

export function contrast(a: string, b: string): number {
  const [high, low] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (high + 0.05) / (low + 0.05);
}

function toHsl(hex: string): [number, number, number] {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255);
  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  const l = (max + min) / 2;
  if (max === min) return [0, 0, l * 100];
  const d = max - min;
  const s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
  const h = max === r ? (g - b) / d + (g < b ? 6 : 0) : max === g ? (b - r) / d + 2 : (r - g) / d + 4;
  return [h * 60, s * 100, l * 100];
}

function toHex(h: number, s: number, l: number): string {
  const a = (s / 100) * Math.min(l / 100, 1 - l / 100);
  const channel = (n: number) => {
    const k = (n + h / 30) % 12;
    const value = l / 100 - a * Math.max(-1, Math.min(k - 3, 9 - k, 1));
    return Math.round(value * 255).toString(16).padStart(2, "0");
  };
  return `#${channel(0)}${channel(8)}${channel(4)}`.toUpperCase();
}

/** The picked colour if it passes, else the nearest darker or lighter shade that does. */
function nearestPassing(hex: string, towards: "darker" | "lighter", passes: (c: string) => boolean): string {
  if (passes(hex)) return hex;
  const [h, s, l] = toHsl(hex);
  for (let step = 1; step <= 100; step++) {
    const lightness = towards === "darker" ? l - step : l + step;
    if (lightness < 0 || lightness > 100) break;
    const shade = toHex(h, s, lightness);
    if (passes(shade)) return shade;
  }
  return towards === "darker" ? "#000000" : "#FFFFFF";
}

/**
 * A colour an Administrator picked, as a light-mode and a dark-mode shade that
 * stay readable on every surface: darkened for light mode, lightened for dark
 * mode, only as far as needed.
 */
export function customSwatch(hex: string, role: "primary" | "accent"): Swatch {
  const needs = NEEDS[role];
  const surfaces = role === "primary" ? SURFACES : { light: ["#FFFFFF"], dark: ["#13202F"] };
  const readableOn = (list: string[]) => (c: string) => list.every((bg) => contrast(c, bg) >= needs);
  const colour = hex.toUpperCase();
  return {
    key: colour,
    name: "Custom",
    light: nearestPassing(colour, "darker", readableOn(surfaces.light)),
    dark: nearestPassing(colour, "lighter", readableOn(surfaces.dark)),
  };
}

export function isCustom(value: string): boolean {
  return value.startsWith("#");
}

/** The swatch for a stored value: one of the list, or the site's own pick. */
export function swatchFor(value: string, role: "primary" | "accent"): Swatch | undefined {
  if (isCustom(value)) return customSwatch(value, role);
  return (role === "primary" ? PRIMARY : ACCENT).find((s) => s.key === value);
}

export interface ColourChoice {
  primary: string | null;
  accent: string | null;
}

/** What applies: the site's colours when enforced, else the person's own, else the site's. */
export function effectiveColours(
  site: { primary_colour: string; accent_colour: string; enforce_colours: boolean },
  own: ColourChoice | null | undefined,
): { primary: string; accent: string } {
  if (site.enforce_colours || !own) {
    return { primary: site.primary_colour, accent: site.accent_colour };
  }
  return {
    primary: own.primary ?? site.primary_colour,
    accent: own.accent ?? site.accent_colour,
  };
}

/** The colours a page gets in one mode, for previews. */
export function paletteFor(
  colours: { primary: string; accent: string },
  mode: "light" | "dark",
): { link: string; buttonBg: string; buttonText: string; accent: string } {
  const primary = swatchFor(colours.primary, "primary") ?? PRIMARY[0];
  const accent = swatchFor(colours.accent, "accent") ?? ACCENT[0];
  const brand = primary.key === DEFAULT_PRIMARY;
  return {
    link: primary[mode],
    buttonBg: brand ? INK_BUTTON[mode].bg : primary[mode],
    buttonText: brand ? INK_BUTTON[mode].text : ON_PRIMARY[mode],
    accent: accent[mode],
  };
}

/** The page's current mode, after the person's choice or the device's setting. */
export function currentMode(): "light" | "dark" {
  const chosen = document.documentElement.dataset.theme;
  if (chosen === "light" || chosen === "dark") return chosen;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

/**
 * Set the colours on the page. Þing's own (Fjord and Lyng) come from
 * tokens.css, so they clear any override: the primary button stays ink and snow
 * as docs/brand asks. Set through the CSSOM, which the page's CSP allows.
 */
export function applyColours(colours: { primary: string; accent: string }): void {
  const root = document.documentElement.style;
  const mode = currentMode();
  const primary = swatchFor(colours.primary, "primary");
  const accent = swatchFor(colours.accent, "accent");
  for (const name of ["--link", "--button-bg", "--button-text", "--accent"]) {
    root.removeProperty(name);
  }
  if (primary && primary.key !== DEFAULT_PRIMARY) {
    root.setProperty("--link", primary[mode]);
    root.setProperty("--button-bg", primary[mode]);
    root.setProperty("--button-text", ON_PRIMARY[mode]);
  }
  if (accent && accent.key !== DEFAULT_ACCENT) root.setProperty("--accent", accent[mode]);
}
