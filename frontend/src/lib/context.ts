import { getContext, setContext } from "svelte";
import type { CustomerDetail } from "./customers.js";

// What a customer's layout shares with the pages under it: the loaded record,
// and a way to replace or reload it after a change.

export interface Loaded<T> {
  readonly current: T | null;
  use(found: T): void;
  reload(): Promise<void>;
}

const CUSTOMER = Symbol("customer");

export function shareCustomer(customer: Loaded<CustomerDetail>): void {
  setContext(CUSTOMER, customer);
}

export function sharedCustomer(): Loaded<CustomerDetail> {
  return getContext<Loaded<CustomerDetail>>(CUSTOMER);
}
