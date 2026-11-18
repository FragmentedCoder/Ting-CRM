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
  /** The town on the address's postcode line. */
  town: string | null;
  people: number | null;
  /** Who usually works with it (its assigned technicians), and whether you do. */
  worked_on_by: string[] | null;
  mine: boolean | null;
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

export type CustomerFilter = "all" | "mine" | "departing" | "former";

/** The All customers chips, each with the customers it shows; "Mine" only when
 *  you usually work with any, and a status only when a customer has it. */
export function customerFilters(
  customers: CustomerSummary[],
): { value: CustomerFilter; label: string; customers: CustomerSummary[] }[] {
  const all = { value: "all" as const, label: "All", customers };
  const narrower: { value: CustomerFilter; label: string; customers: CustomerSummary[] }[] = [
    { value: "mine", label: "Mine", customers: customers.filter((c) => c.mine) },
    { value: "departing", label: "Departing", customers: customers.filter((c) => c.status === "departing") },
    { value: "former", label: "Former", customers: customers.filter((c) => c.status === "former") },
  ];
  return [all, ...narrower.filter((f) => f.customers.length)];
}

/** "12 34 56 78": a CVR number in the groups people read it in. */
export function formatCvr(cvr: string | null): string {
  return cvr ? cvr.replace(/(\d{2})(?=\d)/g, "$1 ") : "—";
}
