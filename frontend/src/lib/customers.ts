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

export type SystemGroup = "servers" | "network" | "cloud" | "printers" | "other";
export type SystemType =
  | "physical_server" | "virtual_machine" | "nas" | "backup_server" | "firewall" | "router"
  | "switch" | "wireless" | "printer" | "m365_tenant" | "other";

export interface System {
  id: number;
  group: SystemGroup;
  type: SystemType;
  name: string;
  /** What it does: "DC and file server". */
  role: string;
  site_id: number | null;
  /** The host a virtual machine runs on. */
  parent_id: number | null;
  hostname: string;
  ip: string;
  hardware: string;
  serial: string;
  os: string;
  in_service_since: string | null;
  warranty_end: string | null;
  retired_on: string | null;
  updates_itself: boolean | null;
  may_update_in_working_hours: boolean | null;
  update_rhythm: string;
  last_update: string | null;
  monitoring: string;
  backup: string;
  notes: string;
}

export const SYSTEM_GROUPS: Record<SystemGroup, string> = {
  servers: "Servers",
  network: "Network",
  cloud: "Cloud",
  printers: "Printers",
  other: "Other",
};

export const SYSTEM_TYPES: Record<SystemType, string> = {
  physical_server: "Physical server",
  virtual_machine: "Virtual machine",
  nas: "NAS",
  backup_server: "Backup server",
  firewall: "Firewall",
  router: "Router",
  switch: "Switch",
  wireless: "Wireless",
  printer: "Printer",
  m365_tenant: "Microsoft 365 tenant",
  other: "Other",
};

export const emptySystem = (): Omit<System, "id"> => ({
  group: "servers", type: "physical_server", name: "", role: "", site_id: null, parent_id: null,
  hostname: "", ip: "", hardware: "", serial: "", os: "", in_service_since: null,
  warranty_end: null, retired_on: null, updates_itself: null, may_update_in_working_hours: null,
  update_rhythm: "", last_update: null, monitoring: "", backup: "", notes: "",
});

/** The side list's groups: Servers, Network, Cloud, Printers and Other, each with its
 *  hosts followed by what runs on them, and retired systems last. */
export function systemGroups(systems: System[]): { key: SystemGroup | "retired"; label: string; systems: { system: System; guest: boolean }[] }[] {
  const active = systems.filter((s) => !s.retired_on);
  const ids = new Set(active.map((s) => s.id));
  const guestsOf = (host: number) => active.filter((s) => s.parent_id === host);
  const groups = (Object.keys(SYSTEM_GROUPS) as SystemGroup[]).map((key) => {
    const tops = active.filter((s) => s.group === key && (s.parent_id === null || !ids.has(s.parent_id)));
    const rows = tops.flatMap((host) => [
      { system: host, guest: false },
      ...guestsOf(host.id).map((guest) => ({ system: guest, guest: true })),
    ]);
    return { key, label: SYSTEM_GROUPS[key], systems: rows };
  });
  const retired = systems.filter((s) => s.retired_on).map((system) => ({ system, guest: false }));
  return [...groups, { key: "retired" as const, label: "Retired", systems: retired }].filter((g) => g.systems.length);
}

export type CaseKind = "" | "monthly" | "standing" | "project";

/** A detail of a customer's service, filled in. */
export interface ServiceDetail {
  key: string;
  label: string;
  kind: "text" | "number" | "date" | "yes_no" | "choice";
  choices: string[];
  help: string;
  value: string | number | boolean | null;
  /** Added for this customer, not from the standard. */
  added: boolean;
  /** Dropped from the standard since, kept with what was filled in. */
  kept: boolean;
}

/** A customer's copy of a standard service (backend/app/customer_services.py). */
export interface CustomerService {
  id: number;
  standard_service_id: number | null;
  name: string;
  status: "active" | "ended";
  started_on: string | null;
  ended_on: string | null;
  company_id: number | null;
  details: ServiceDetail[];
  /** Standard details this customer doesn't need. */
  not_used: { key: string; label: string }[];
  systems: { system_id: number; note: string }[];
  /** The case number its work goes on ("Log time on"). */
  case_number: string;
  case_kind: CaseKind;
  case_history: { number: string; kind: CaseKind; until: string }[];
  notes: string;
  /** The active agreement section that covers it; null means "No agreement". */
  agreement: { agreement_id: number; name: string; section: string } | null;
}

export type AgreementKind = "service" | "dpa" | "quote" | "email" | "other";
export type AgreementStatus = "offer" | "active" | "ended";

export interface AgreementVersion {
  number: number;
  sent_on: string | null;
  signed_on: string | null;
  signed_for_customer: string;
  signed_for_us: string;
  note: string;
}

export interface AgreementSection {
  /** The section's number in the document: "§ 3.1". */
  ref: string;
  text: string;
  /** The customer service it covers. */
  service_id: number | null;
  terms: boolean;
}

/** What was signed, and what it covers (backend/app/agreements.py). */
export interface Agreement {
  id: number;
  name: string;
  kind: AgreementKind;
  status: AgreementStatus;
  starts_on: string | null;
  /** The end of the current term, or the day it ended. */
  ends_on: string | null;
  /** The last day to give notice. */
  notice_by: string | null;
  auto_renews: boolean;
  company_id: number | null;
  notice_period: string;
  sla: string;
  price_section: string;
  versions: AgreementVersion[];
  sections: AgreementSection[];
  notes: string;
}

export const AGREEMENT_KINDS: Record<AgreementKind, string> = {
  service: "Service agreement",
  dpa: "Data processing agreement",
  quote: "Accepted quote",
  email: "Confirmed by email",
  other: "Other",
};

export const emptyAgreement = (): Omit<Agreement, "id"> => ({
  name: "", kind: "service", status: "active", starts_on: null, ends_on: null, notice_by: null,
  auto_renews: false, company_id: null, notice_period: "", sla: "", price_section: "",
  versions: [], sections: [], notes: "",
});

/** The newest version that was signed, else the newest. */
export function currentVersion(agreement: Pick<Agreement, "versions">): AgreementVersion | null {
  const signed = agreement.versions.filter((v) => v.signed_on);
  return (signed.length ? signed : agreement.versions).at(-1) ?? null;
}

/** How a service shows on the overview: green active and covered, yellow active
 *  with no agreement, red no longer provided. Always with its word. */
export function servicePill(service: Pick<CustomerService, "name" | "status" | "agreement">): {
  tone: "ok" | "warning" | "critical";
  text: string;
} {
  if (service.status === "ended") return { tone: "critical", text: `${service.name}: not provided` };
  if (!service.agreement) return { tone: "warning", text: `${service.name}: no agreement` };
  return { tone: "ok", text: service.name };
}

/** The support a customer has, from their Support service's "When it applies". */
export function supportLevel(services: CustomerService[]): { tone: "ok" | "warning"; text: string; hours: string | null } {
  const support = services.find((s) => s.status === "active" && s.details.some((d) => d.key === "when"));
  const when = support?.details.find((d) => d.key === "when")?.value;
  const hours = support?.details.find((d) => d.key === "hours")?.value;
  if (!support || !when || String(when).startsWith("None")) {
    return { tone: "warning", text: "No support", hours: "Each job needs a case number of its own." };
  }
  return { tone: "ok", text: String(when), hours: hours ? String(hours) : null };
}

/** The case numbers to log time on: each active service's, once. */
export function caseNumbers(services: CustomerService[]): { number: string; kind: CaseKind; services: string[] }[] {
  const found = new Map<string, { number: string; kind: CaseKind; services: string[] }>();
  for (const service of services) {
    if (service.status !== "active" || !service.case_number) continue;
    const entry = found.get(service.case_number) ?? { number: service.case_number, kind: service.case_kind, services: [] };
    entry.services.push(service.name);
    found.set(service.case_number, entry);
  }
  return [...found.values()];
}

/** Another company in a group that is one customer, such as a subsidiary. */
export interface Company {
  id: number;
  name: string;
  cvr: string | null;
  address: string;
}

/** A pinned warning: one line every technician sees first on the customer. */
export interface Pin {
  id: number;
  text: string;
  severity: "critical" | "caution";
  /** "Henrik Dahl, Manager"; null once that person is gone. */
  pinned_by: string | null;
  pinned_at: string;
}

export const PINS_PER_CUSTOMER = 3;

/** "Pinned by Henrik Dahl, Manager · 2 of 3": everyone who pinned one, and how many
 *  of the three are used. */
export function pinnedLine(pins: Pin[]): string {
  const by = [...new Set(pins.map((pin) => pin.pinned_by).filter((name) => name !== null))];
  const who = by.length ? `Pinned by ${by.join(" and ")}` : "Pinned";
  return `${who} · ${pins.length} of ${PINS_PER_CUSTOMER}`;
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
  /** The systems at the customer: servers, virtual machines on their host, network, cloud. */
  systems: System[] | null;
  /** What was signed, and which services each agreement covers. */
  agreements: Agreement[] | null;
  /** Create and change agreements (Managers and Administrators). */
  may_manage_agreements: boolean;
  /** The services we provide, each the customer's own copy of a standard service. */
  services: CustomerService[] | null;
  /** The group's other companies; the customer itself is the main one. */
  companies: Company[] | null;
  /** Pinned warnings, hard rules first; at most PINS_PER_CUSTOMER. */
  pins: Pin[] | null;
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
