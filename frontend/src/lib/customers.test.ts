import { describe, expect, it } from "vitest";
import { customerFilters, formatCvr, mainRole, mayContactLine, statusPill, type CustomerSummary } from "./customers.js";

describe("statusPill", () => {
  it("shows every status as a word in its colour", () => {
    expect(statusPill("active")).toEqual({ tone: "ok", text: "Active" });
    expect(statusPill("departing")).toEqual({ tone: "warning", text: "Departing" });
    expect(statusPill("former")).toEqual({ tone: "critical", text: "Former" });
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
