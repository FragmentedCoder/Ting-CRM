import { describe, expect, it } from "vitest";
import {
  caseNumbers, coveredOn, currentVersion, customerFilters, emptySystem, findPeople, formatCvr, inForce, mainRole, otherCustomers, samePeople, servicePill, supportLevel, systemGroups, mayContactLine, pinnedLine, statusLine, statusPill, systemsPreview, type CustomerService, type CustomerSummary, type Pin,
} from "./customers.js";

describe("what covered a service on a day", () => {
  const section = (service_id: number) => ({ ref: "§ 3.1", text: "", service_id, terms: false });
  const agreements = [
    { name: "2026", status: "active" as const, starts_on: "2026-10-05", ends_on: null, sections: [section(1)] },
    { name: "2027", status: "offer" as const, starts_on: null, ends_on: null, sections: [section(1), section(2)] },
    { name: "2025", status: "ended" as const, starts_on: "2025-01-01", ends_on: "2026-08-16", sections: [section(1)] },
  ];
  const by = (day: string, service = 1) => coveredOn(agreements, service, day)?.name ?? null;

  it("is the agreement that ran then, not the one running when it's recorded", () => {
    expect(by("2026-11-24")).toBe("2026");
    expect(by("2026-10-05")).toBe("2026");
    expect(by("2026-06-27")).toBe("2025");
    expect(by("2026-08-16")).toBe("2025");
  });

  it("is none in a gap, before the first began, or for a service only an offer names", () => {
    expect(by("2026-09-10")).toBeNull();
    expect(by("2024-12-31")).toBeNull();
    expect(by("2026-11-24", 2)).toBeNull();
  });

  it("takes an agreement without a start as running from the beginning", () => {
    expect(inForce({ status: "active", starts_on: null, ends_on: null }, "2020-01-01")).toBe(true);
    expect(inForce({ status: "ended", starts_on: null, ends_on: "2026-08-16" }, "2026-08-17")).toBe(false);
    expect(inForce({ status: "offer", starts_on: null, ends_on: null }, "2026-11-24")).toBe(false);
  });
});

describe("choosing who works with a customer", () => {
  it("says what else a technician has, leaving out the customer at hand", () => {
    expect(otherCustomers({ customers: 0 }, false)).toBe("No other customers");
    expect(otherCustomers({ customers: 1 }, true)).toBe("No other customers");
    expect(otherCustomers({ customers: 1 }, false)).toBe("1 other customer");
    expect(otherCustomers({ customers: 5 }, true)).toBe("4 other customers");
    expect(otherCustomers({ customers: null }, false)).toBe("No other customers");
  });

  it("finds people by part of their name or username, whatever the case", () => {
    const people = [
      { display_name: "Astrid Fjeld", username: "astrid" },
      { display_name: "Bo Bager", username: "bob" },
    ];
    expect(findPeople(people, "")).toEqual(people);
    expect(findPeople(people, "  FJE ")).toEqual([people[0]]);
    expect(findPeople(people, "bob")).toEqual([people[1]]);
    expect(findPeople(people, "nobody")).toEqual([]);
  });

  it("knows the same people in another order", () => {
    expect(samePeople([1, 2], [2, 1])).toBe(true);
    expect(samePeople([1, 2], [1])).toBe(false);
    expect(samePeople([1, 2], [1, 3])).toBe(false);
    expect(samePeople([], [])).toBe(true);
  });
});

describe("statusPill", () => {
  it("shows every status as a word in its colour", () => {
    expect(statusPill("active")).toEqual({ tone: "ok", text: "Active" });
    expect(statusPill("departing")).toEqual({ tone: "warning", text: "Departing" });
    expect(statusPill("former")).toEqual({ tone: "critical", text: "Former" });
  });
});

describe("statusLine", () => {
  it("says the status as the header does, with its day", () => {
    const show = (day: string) => `<${day}>`;
    expect(statusLine("active", null, show)).toEqual({ tone: "ok", text: "Active customer" });
    expect(statusLine("departing", "2026-12-31", show)).toEqual({ tone: "warning", text: "Departing on <2026-12-31>" });
    expect(statusLine("departing", null, show)).toEqual({ tone: "warning", text: "Departing" });
    expect(statusLine("former", "2027-01-01", show)).toEqual({
      tone: "critical", text: "Former customer since <2027-01-01>" });
  });
});

describe("systemsPreview", () => {
  it("shows hosts with their virtual machines under them, without the retired", () => {
    const system = (id: number, name: string, extra: object = {}) => ({ ...emptySystem(), id, name, ...extra });
    const systems = [
      system(1, "HV01"), system(2, "DC01", { type: "virtual_machine", parent_id: 1 }),
      system(3, "APP01", { type: "virtual_machine", parent_id: 1 }), system(4, "FW01", { group: "network" }),
      system(5, "OLD01", { retired_on: "2025-01-01" }),
    ];
    const preview = systemsPreview(systems, 3);
    expect(preview.total).toBe(4);
    expect(preview.rows.map((r) => [r.system.name, r.guest, r.host])).toEqual([
      ["HV01", false, true], ["DC01", true, false], ["APP01", true, false]]);
  });
});

describe("formatCvr", () => {
  it("groups a CVR number in pairs, and shows a dash for none", () => {
    expect(formatCvr("12345678")).toBe("12 34 56 78");
    expect(formatCvr(null)).toBe("—");
  });
});

function customer(name: string, extra: Partial<CustomerSummary> = {}): CustomerSummary {
  return {
    id: name.length, name, visibility: "full", cvr: null, status: "active", status_date: null,
    town: null, people: 0, worked_on_by: [], mine: false, logo_url: null, ...extra,
  };
}

describe("customerFilters", () => {
  it("offers All, then only the filters that show someone, with their customers", () => {
    const nordlys = customer("Nordlys ApS", { mine: true });
    const strand = customer("Strandvejens Revision", { status: "departing" });
    const grenaa = customer("Grenaa Bådeværft", { status: "former" });
    const filters = customerFilters([nordlys, strand, grenaa]);
    expect(filters.map((f) => [f.value, f.customers.map((c) => c.name)])).toEqual([
      ["all", ["Nordlys ApS", "Strandvejens Revision", "Grenaa Bådeværft"]],
      ["mine", ["Nordlys ApS"]],
      ["departing", ["Strandvejens Revision"]],
      ["former", ["Grenaa Bådeværft"]],
    ]);
    expect(customerFilters([customer("Birkely")]).map((f) => f.value)).toEqual(["all"]);
    // Needs attention, for the customers that do.
    const needing = customerFilters([nordlys, strand, grenaa], [strand.id]);
    expect(needing.map((f) => [f.value, f.customers.length])).toEqual([
      ["all", 3], ["mine", 1], ["attention", 1], ["departing", 1], ["former", 1]]);
    expect(needing[2].customers[0].name).toBe("Strandvejens Revision");
  });
});

describe("contact cards", () => {
  it("show the most telling role first", () => {
    expect(mainRole({ roles: ["billing", "decision_maker"] })).toBe("Decision-maker");
    expect(mainRole({ roles: [] })).toBeNull();
  });

  it("say whether we may call, and how", () => {
    expect(mayContactLine({ may_contact: true, may_contact_note: "", preferred_channel: "phone" }))
      .toEqual({ tone: "ok", text: "May be contacted, by phone" });
    expect(mayContactLine({ may_contact: false, may_contact_note: "Only about the server room", preferred_channel: "" }))
      .toEqual({ tone: "warning", text: "Only about the server room" });
    expect(mayContactLine({ may_contact: false, may_contact_note: "", preferred_channel: "email" }))
      .toEqual({ tone: "warning", text: "Don't contact" });
  });
});

describe("pinnedLine", () => {
  const pin = (id: number, by: string | null): Pin =>
    ({ id, text: "x", severity: "caution", pinned_by: by, pinned_at: "2026-10-27T12:00:00Z" });

  it("names who pinned them and how many of three are used", () => {
    expect(pinnedLine([pin(1, "Henrik Dahl, Manager"), pin(2, "Henrik Dahl, Manager")]))
      .toBe("Pinned by Henrik Dahl, Manager · 2 of 3");
    expect(pinnedLine([pin(1, "Henrik Dahl, Manager"), pin(2, "Ingrid Admin, Administrator")]))
      .toBe("Pinned by Henrik Dahl, Manager and Ingrid Admin, Administrator · 2 of 3");
    expect(pinnedLine([pin(1, null)])).toBe("Pinned · 1 of 3");
  });
});

describe("systemGroups", () => {
  const system = (id: number, name: string, extra: object = {}) => ({ ...emptySystem(), id, name, ...extra });

  it("puts each guest under its host, and retired systems last", () => {
    const hv01 = system(1, "HV01");
    const dc01 = system(2, "DC01", { type: "virtual_machine", parent_id: 1 });
    const fw01 = system(3, "FW01", { group: "network", type: "firewall" });
    const srv01 = system(4, "SRV01", { retired_on: "2025-06-30" });
    const groups = systemGroups([hv01, dc01, fw01, srv01]);
    expect(groups.map((g) => [g.label, g.systems.map((s) => `${s.guest ? "  " : ""}${s.system.name}`)])).toEqual([
      ["Servers", ["HV01", "  DC01"]],
      ["Network", ["FW01"]],
      ["Retired", ["SRV01"]],
    ]);
  });
});

describe("the overview's support and case numbers", () => {
  const service = (name: string, extra: Partial<CustomerService> = {}): CustomerService => ({
    id: name.length, standard_service_id: 1, name, status: "active", started_on: null, ended_on: null,
    company_id: null, details: [], not_used: [], systems: [], case_number: "", case_kind: "",
    case_history: [], notes: "", agreement: null, ...extra,
  });
  const detail = (key: string, value: string) =>
    ({ key, label: key, kind: "text" as const, choices: [], help: "", value, added: false, kept: false });

  it("shows the support from the Support service, or none", () => {
    const support = service("Support", { details: [detail("when", "Working hours"), detail("hours", "08:00 to 16:00")] });
    expect(supportLevel([support])).toEqual({ tone: "ok", text: "Working hours", hours: "08:00 to 16:00" });
    expect(supportLevel([]).text).toBe("No support");
    expect(supportLevel([service("Support", { details: [detail("when", "None: each job its own case")] })]).text)
      .toBe("No support");
  });

  it("lists each active service's case number once", () => {
    const found = caseNumbers([
      service("Support", { case_number: "TDSE26114", case_kind: "monthly" }),
      service("Updates and maintenance", { case_number: "TDSE26114", case_kind: "monthly" }),
      service("Backup", { case_number: "TDSE26031", case_kind: "standing" }),
      service("Antivirus", { case_number: "TDSE25002", status: "ended" }),
    ]);
    expect(found).toEqual([
      { number: "TDSE26114", kind: "monthly", services: ["Support", "Updates and maintenance"] },
      { number: "TDSE26031", kind: "standing", services: ["Backup"] },
    ]);
  });
});

describe("agreements", () => {
  const version = (number: number, signed_on: string | null) =>
    ({ number, sent_on: null, signed_on, signed_for_customer: "", signed_for_us: "", note: "" });

  it("take the newest signed version as the current one", () => {
    expect(currentVersion({ versions: [version(1, "2024-01-10"), version(2, "2024-03-18"), version(3, null)] })?.number).toBe(2);
    expect(currentVersion({ versions: [version(1, null)] })?.number).toBe(1);
    expect(currentVersion({ versions: [] })).toBeNull();
  });

  it("colour a service by whether an agreement covers it", () => {
    const covered = { agreement_id: 1, name: "Service agreement 2024", section: "§ 3.1" };
    expect(servicePill({ name: "Backup", status: "active", agreement: covered })).toEqual({ tone: "ok", text: "Backup" });
    expect(servicePill({ name: "Printers", status: "active", agreement: null }))
      .toEqual({ tone: "warning", text: "Printers: no agreement" });
    expect(servicePill({ name: "Antivirus", status: "ended", agreement: null }))
      .toEqual({ tone: "critical", text: "Antivirus: not provided" });
  });
});
