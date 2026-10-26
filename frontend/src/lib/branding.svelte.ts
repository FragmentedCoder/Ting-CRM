import { api } from "./api";

export interface Branding {
  site_name: string;
  tagline: string;
  company_name: string | null;
  logo_url: string | null;
  primary_colour: string;
  accent_colour: string;
  enforce_colours: boolean;
}

const DEFAULTS: Branding = {
  site_name: "Þing",
  tagline: "Reports worth keeping.",
  company_name: null,
  logo_url: null,
  primary_colour: "fjord",
  accent_colour: "rav",
  enforce_colours: false,
};

// The site's name, tag line, logo and colours, which an Administrator can change.
// Public: the sign-in page shows them too.
export const branding = $state<{ current: Branding; loaded: boolean }>({
  current: DEFAULTS,
  loaded: false,
});

let loading: Promise<void> | null = null;

export function loadBranding(): Promise<void> {
  loading ??= api<Branding>("GET", "/branding")
    .then((found) => {
      branding.current = found;
    })
    .catch(() => {
      // Keep the defaults; the page works without the custom look.
    })
    .finally(() => {
      branding.loaded = true;
    });
  return loading;
}

export function useBranding(found: Branding): void {
  branding.current = found;
}

/** The browser tab's title: the page, then the site's name. */
export function pageTitle(page: string): string {
  return `${page} · ${branding.current.site_name}`;
}
