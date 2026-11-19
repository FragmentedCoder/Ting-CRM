import { describe, expect, it } from "vitest";
import { hitPath, opensSearch } from "./search.js";

describe("a hit", () => {
  it("opens on the customer's page that shows it", () => {
    expect(hitPath({ page: "overview", record_id: null })).toEqual({ page: "", query: "" });
    expect(hitPath({ page: "contacts", record_id: null })).toEqual({ page: "/contacts", query: "" });
    expect(hitPath({ page: "systems", record_id: 7 })).toEqual({ page: "/systems", query: "?system=7" });
    expect(hitPath({ page: "services", record_id: 3 })).toEqual({ page: "/services", query: "?service=3" });
    expect(hitPath({ page: "services", record_id: null })).toEqual({ page: "/services", query: "" });
  });
});

describe("the keys that open search", () => {
  const key = (k: string, extra: Partial<{ ctrlKey: boolean; metaKey: boolean; altKey: boolean }> = {}) => ({
    key: k, ctrlKey: false, metaKey: false, altKey: false, ...extra,
  });

  it("are Ctrl+K or ⌘K anywhere, even while typing", () => {
    expect(opensSearch(key("k", { ctrlKey: true }), true)).toBe(true);
    expect(opensSearch(key("K", { metaKey: true }), false)).toBe(true);
    expect(opensSearch(key("k"), false)).toBe(false);
    expect(opensSearch(key("k", { ctrlKey: true, altKey: true }), false)).toBe(false);
  });

  it("and a slash, but not in a field", () => {
    expect(opensSearch(key("/"), false)).toBe(true);
    expect(opensSearch(key("/"), true)).toBe(false);
    expect(opensSearch(key("/", { ctrlKey: true }), false)).toBe(false);
  });
});
