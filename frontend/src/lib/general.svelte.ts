import { api } from "./api";
import { addInterval, today } from "./planning.js";

// The team's general settings (backend/app/general.py): how Þing behaves for
// everyone. Read by every page that needs them; changed in the admin panel.
export interface General {
  /** How far ahead what's coming up is shown and warned about, in months. */
  warn_ahead_months: number;
  /** Work ticked off from a task or a renewal is marked Covered or Billable. */
  cover_ticked_off_work: boolean;
  /** A new customer's overview shows the Getting started steps. */
  getting_started: boolean;
  /** The country code offered first for a phone number: "+45". */
  phone_country_code: string;
}

const DEFAULTS: General = {
  warn_ahead_months: 12,
  cover_ticked_off_work: true,
  getting_started: true,
  phone_country_code: "+45",
};

/** What the admin panel offers for how far ahead: three months to three years. */
export const AHEAD_MONTHS = [3, 6, 12, 18, 24, 36];

export const general = $state<{ current: General; loaded: boolean }>({
  current: DEFAULTS,
  loaded: false,
});

let loading: Promise<void> | null = null;

/** Fetches the settings once; the pages work on the defaults until they arrive. */
export function loadGeneral(again = false): Promise<void> {
  if (again) loading = null;
  loading ??= api<General>("GET", "/general")
    .then((found) => {
      general.current = found;
    })
    .catch(() => {
      // Keep what there is: the defaults are how Þing behaves unless told otherwise.
    })
    .finally(() => {
      general.loaded = true;
    });
  return loading;
}

export function useGeneral(found: General): void {
  general.current = found;
}

/** The last day that counts as coming up: further off, something waits on its own
 *  page without a warning. */
export function aheadUntil(now = today(), months = general.current.warn_ahead_months): string {
  return addInterval(now, { count: months, unit: "months" });
}

/** "3 months", "year", "18 months", "2 years": for "the next …". */
export function aheadWords(months = general.current.warn_ahead_months): string {
  if (months % 12 === 0) return months === 12 ? "year" : `${months / 12} years`;
  return `${months} months`;
}
