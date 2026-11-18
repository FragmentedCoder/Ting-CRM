import { api } from "./api.js";

/** The CVR lookup's settings (backend/app/cvr.py). Off until an Administrator
 *  switches it on, with the contact cvrapi.dk asks for. */
export interface CvrSettings {
  enabled: boolean;
  contact: string;
}

/** A company from the CVR register: its address with postcode and town on the
 *  second line. */
export interface CvrCompany {
  cvr: string;
  name: string;
  address: string;
}

let enabled: Promise<boolean> | null = null;

/** Whether the forms offer a lookup; asked once per page load. */
export function cvrLookupEnabled(): Promise<boolean> {
  enabled ??= api<{ enabled: boolean }>("GET", "/cvr/status").then((s) => s.enabled).catch(() => false);
  return enabled;
}

export function lookUpCvr(search: string): Promise<CvrCompany> {
  return api<CvrCompany>("GET", `/cvr?search=${encodeURIComponent(search)}`);
}
