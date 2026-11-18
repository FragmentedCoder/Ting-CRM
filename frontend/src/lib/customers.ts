import type { Role } from "./roles.js";

/** How much of a customer someone sees (backend/app/customers.py). */
export type Visibility = "full" | "metadata";

/** Active, departing (with the day it leaves) or former (with the day it left). */
export type CustomerStatus = "active" | "departing" | "former";

export type SiteKind = "main" | "office" | "production" | "warehouse" | "group_company" | "other";
export type ContactRole = "primary" | "technical" | "billing" | "decision_maker" | "security";
export type Channel = "" | "phone" | "email";

export interface Site {
  id: number;
  name: string;
  kind: SiteKind;
  address: string;
  opening_hours: string;
  access: string;
  parking: string;
  note: string;
  /** The site's own contact: one of the customer's contacts. */
  contact_id: number | null;
}

export interface Contact {
  id: number;
  name: string;
  /** Their title at the customer: the role line on the card. */
  role: string;
  email: string;
  phone: string;
  /** What they are to us. */
  roles: ContactRole[];
  /** The site they're at; none for the whole company. */
  site_id: number | null;
  may_contact: boolean;
  may_contact_note: string;
  preferred_channel: Channel;
}

export const SITE_KINDS: Record<SiteKind, string> = {
  main: "Main site",
  office: "Office",
  production: "Production",
  warehouse: "Warehouse",
  group_company: "Group company",
  other: "Other",
};

/** In the order a card shows the first of them. */
export const CONTACT_ROLES: Record<ContactRole, string> = {
  decision_maker: "Decision-maker",
  primary: "Primary contact",
  technical: "Technical contact",
  security: "Security and NIS2 contact",
  billing: "Billing",
};

/** The role a contact card shows: the first they have, in CONTACT_ROLES' order. */
export function mainRole(contact: Pick<Contact, "roles">): string | null {
  const found = (Object.keys(CONTACT_ROLES) as ContactRole[]).find((r) => contact.roles.includes(r));
  return found ? CONTACT_ROLES[found] : null;
}

/** What the card says about calling them: green when we may, yellow with the
 *  restriction or a plain "Don't contact" when we may not. */
export function mayContactLine(contact: Pick<Contact, "may_contact" | "may_contact_note" | "preferred_channel">): {
  tone: "ok" | "warning";
  text: string;
} {
  if (!contact.may_contact) return { tone: "warning", text: contact.may_contact_note || "Don't contact" };
  const channel = contact.preferred_channel === "phone" ? ", by phone" : contact.preferred_channel === "email" ? ", by email" : "";
  return { tone: "ok", text: (contact.may_contact_note || "May be contacted") + channel };
}

export const emptyContact = (): Omit<Contact, "id"> => ({
  name: "", role: "", email: "", phone: "", roles: [], site_id: null, may_contact: true,
  may_contact_note: "", preferred_channel: "",
});

export const emptySite = (): Omit<Site, "id"> => ({
  name: "", kind: "other", address: "", opening_hours: "", access: "", parking: "", note: "",
  contact_id: null,
});

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
