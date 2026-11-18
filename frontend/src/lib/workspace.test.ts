import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  chooseCustomer,
  clearWorkspace,
  noteViewed,
  recentCustomers,
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

  it("remembers the customers looked at last, the latest first, while they're still listed", async () => {
    serve([nordlys, fjeldstue]);
    await refreshWorkspace();
    noteViewed(1);
    noteViewed(2);
    noteViewed(1);
    expect(workspace.recent).toEqual([1, 2]);
    expect(recentCustomers().map((c) => c.name)).toEqual(["Nordlys IT ApS", "Fjeldstue A/S"]);
    for (const id of [3, 4, 5, 6, 7]) noteViewed(id);
    expect(workspace.recent).toEqual([7, 6, 5, 4, 3, 1]);
    // One that's gone from the list is left out.
    expect(recentCustomers().map((c) => c.name)).toEqual(["Nordlys IT ApS"]);
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
