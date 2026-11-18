import type { Role } from "./roles.js";

/** How much of a customer someone sees (backend/app/customers.py). */
export type Visibility = "full" | "metadata";

/** Active, departing (with the day it leaves) or former (with the day it left). */
export type CustomerStatus = "active" | "departing" | "former";

export interface Site {
  id: number;
  name: string;
  address: string;
}

export interface Contact {
  id: number;
  name: string;
  role: string;
  email: string;
  phone: string;
}

export interface Person {
  id: number;
  username: string;
  display_name: string;
  roles: Role[];
}

export interface CustomerSummary {
  id: number;
  name: string;
  visibility: Visibility;
  cvr: string | null;
  status: CustomerStatus | null;
  /** The day a departing customer leaves, or a former one left. */
  status_date: string | null;
  people: number | null;
  logo_url: string | null;
}

export interface CustomerDetail extends CustomerSummary {
  address: string | null;
  retention_months: number | null;
  created_at: string | null;
  sites: Site[] | null;
  contacts: Contact[] | null;
  /** The technicians assigned to the customer. */
  assigned: Person[] | null;
  may_manage: boolean;
  may_edit: boolean;
  may_delete: boolean;
  assignable: Person[] | null;
}

export const STATUS_NAMES: Record<CustomerStatus, string> = {
  active: "Active",
  departing: "Departing",
  former: "Former",
};

/** The status as a pill: green active, yellow departing, red former (always a word). */
export function statusPill(status: CustomerStatus): { tone: "ok" | "warning" | "critical"; text: string } {
  const tone = status === "active" ? "ok" : status === "departing" ? "warning" : "critical";
  return { tone, text: STATUS_NAMES[status] };
}

/** "12 34 56 78": a CVR number in the groups people read it in. */
export function formatCvr(cvr: string | null): string {
  return cvr ? cvr.replace(/(\d{2})(?=\d)/g, "$1 ") : "—";
}
