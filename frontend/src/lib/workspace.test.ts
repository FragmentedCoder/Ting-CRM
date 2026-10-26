import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  chooseCustomer,
  clearWorkspace,
  refreshSoon,
  refreshWorkspace,
  workspace,
} from "./workspace.svelte";

const { api } = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", () => ({ api }));

const nordlys = { id: 1, name: "Nordlys IT ApS", visibility: "full" };
const fjeldstue = { id: 2, name: "Fjeldstue A/S", visibility: "full" };

/** The server's answers: the customers listed. */
function serve(customers: unknown[] | Error) {
  api.mockImplementation(async (_method: string, path: string) => {
    if (path === "/customers") {
      if (customers instanceof Error) throw customers;
      return customers;
    }
    return [];
  });
}

beforeEach(() => {
  api.mockReset();
  clearWorkspace();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("the workspace", () => {
  it("drops the open customer once it's no longer listed, and counts the check", async () => {
    serve([nordlys, fjeldstue]);
    await chooseCustomer(1);
    expect(workspace.customerId).toBe(1);
    const before = workspace.checks;

    serve([fjeldstue]);
    await refreshWorkspace();
    expect(workspace.customerId).toBeNull();
    expect(workspace.customers?.map((c) => c.name)).toEqual(["Fjeldstue A/S"]);
    expect(workspace.checks).toBe(before + 1);
  });

  it("keeps what it has when the list can't be fetched", async () => {
    serve([nordlys]);
    await chooseCustomer(1);
    const before = workspace.checks;

    serve(new Error("offline"));
    await refreshWorkspace();
    expect(workspace.customerId).toBe(1);
    expect(workspace.customers?.map((c) => c.name)).toEqual(["Nordlys IT ApS"]);
    expect(workspace.checks).toBe(before);
  });

  it("refreshes on a page change at most every 15 seconds", async () => {
    vi.useFakeTimers();
    serve([nordlys]);
    await refreshWorkspace();
    const calls = api.mock.calls.length;

    refreshSoon();
    expect(api.mock.calls.length).toBe(calls);
    vi.advanceTimersByTime(16_000);
    refreshSoon();
    expect(api.mock.calls.length).toBe(calls + 1);
  });
});
