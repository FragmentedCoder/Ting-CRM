const DATE_TIME = new Intl.DateTimeFormat("en-GB", { dateStyle: "medium", timeStyle: "short" });
const DATE = new Intl.DateTimeFormat("en-GB", { dateStyle: "medium" });
// A plain date ("2026-10-01") parses as midnight UTC; shown in UTC, it's the same day everywhere.
const PLAIN_DATE = new Intl.DateTimeFormat("en-GB", { dateStyle: "medium", timeZone: "UTC" });

/** "24 Oct 2026, 14:05" in the viewer's time zone; "Never" when there is no date. */
export function dateTime(iso: string | null | undefined, empty = "Never"): string {
  return iso ? DATE_TIME.format(new Date(iso)) : empty;
}

export function date(iso: string | null | undefined, empty = "—"): string {
  if (!iso) return empty;
  return (/^\d{4}-\d{2}-\d{2}$/.test(iso) ? PLAIN_DATE : DATE).format(new Date(iso));
}

/** ISO 8601 in UTC to the second ("2026-10-25T14:05:12Z"), as the audit log shows times. */
export function isoTime(iso: string): string {
  return new Date(iso).toISOString().replace(/\.\d{3}Z$/, "Z");
}

/** A period's dates (an agreement's, say): both, "From …" or "Until …" when only one is set, or a dash. */
export function dateRange(start: string | null | undefined, end: string | null | undefined): string {
  if (start && end) return `${date(start)} – ${date(end)}`;
  if (start) return `From ${date(start)}`;
  if (end) return `Until ${date(end)}`;
  return "—";
}

/** A short, readable name for a browser from its user agent. */
export function browserName(userAgent: string | null): string {
  if (!userAgent) return "Unknown browser";
  const known: [RegExp, string][] = [
    [/Edg\//, "Edge"],
    [/Firefox\//, "Firefox"],
    [/Chrome\//, "Chrome"],
    [/Safari\//, "Safari"],
  ];
  const name = known.find(([pattern]) => pattern.test(userAgent))?.[1] ?? "Browser";
  const system = /Windows/.test(userAgent)
    ? "Windows"
    : /Mac OS X/.test(userAgent)
      ? "macOS"
      : /Android/.test(userAgent)
        ? "Android"
        : /iPhone|iPad/.test(userAgent)
          ? "iOS"
          : /Linux/.test(userAgent)
            ? "Linux"
            : null;
  return system ? `${name} on ${system}` : name;
}

const UNITS = ["bytes", "KB", "MB", "GB", "TB"];

/** "1.4 GB": sizes in powers of 1024, with one decimal from KB up. */
export function bytes(size: number): string {
  let value = size;
  let unit = 0;
  while (value >= 1024 && unit < UNITS.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return unit === 0 ? `${value} ${UNITS[0]}` : `${value.toFixed(1)} ${UNITS[unit]}`;
}

/** "3 days, 4 hours": how long since a moment, roughly. */
export function since(iso: string, now = Date.now()): string {
  const minutes = Math.max(0, Math.floor((now - Date.parse(iso)) / 60_000));
  const days = Math.floor(minutes / 1440);
  const hours = Math.floor((minutes % 1440) / 60);
  const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;
  if (days) return `${plural(days, "day")}, ${plural(hours, "hour")}`;
  if (hours) return `${plural(hours, "hour")}, ${plural(minutes % 60, "minute")}`;
  return plural(minutes, "minute");
}

const TIME = new Intl.DateTimeFormat("en-GB", { timeStyle: "medium" });

/** "14:05:09" in the viewer's time zone. */
export function time(iso: string): string {
  return TIME.format(new Date(iso));
}
