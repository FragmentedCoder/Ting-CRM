<script lang="ts">
  import { goto } from "$app/navigation";
  import { resolve } from "$app/paths";
  import { page } from "$app/state";
  import Building from "@lucide/svelte/icons/building";
  import { untrack, type Snippet } from "svelte";
  import { api, ApiError, sessionGone } from "#lib/api.js";
  import RecordHeader from "#lib/components/RecordHeader.svelte";
  import { shareCustomer } from "#lib/context.js";
  import { formatCvr, type CustomerDetail } from "#lib/customers.js";
  import { toast } from "#lib/toast.svelte.js";
  import { chooseCustomer, refreshWorkspace, workspace } from "#lib/workspace.svelte.js";

  // A customer's pages share this: the customer (loaded once per customer), its
  // header, and the side menu opened on it.
  let { children }: { children: Snippet } = $props();

  let customer = $state<CustomerDetail | null>(null);
  let error = $state<string | null>(null);

  const id = $derived(page.params.id ?? "");
  let leaving = false;

  // Access that ends while the customer is open (you're unassigned, it's deleted):
  // it leaves the menu, and you go to the customers you still have.
  async function lost(name: string) {
    if (leaving) return;
    leaving = true;
    toast(`You no longer have access to ${name}.`, "warning", { key: "access" });
    await refreshWorkspace();
    await goto(resolve("/(app)/customers"), { replace: true });
  }

  async function load() {
    const wanted = Number(id);
    // Known from before: the customer you had open, or one the menu still lists.
    const known = (customer?.id === wanted ? customer.name : null)
      ?? workspace.customers?.find((c) => c.id === wanted)?.name;
    try {
      customer = await api<CustomerDetail>("GET", `/customers/${id}`);
      error = null;
    } catch (e) {
      if (e instanceof ApiError && e.status === 404 && known) {
        void lost(known);
        return;
      }
      customer = null;
      if (!sessionGone(e)) error = e instanceof ApiError ? e.message : "Not found.";
    }
  }

  // The menu's list of customers is refreshed now and then; one gone from it is
  // gone here too.
  $effect(() => {
    const listed = workspace.customers;
    if (listed && customer && !listed.some((c) => c.id === customer?.id)) void lost(customer.name);
  });

  shareCustomer({
    get current() {
      return customer;
    },
    use(found) {
      customer = found;
      void refreshWorkspace();
    },
    async reload() {
      await load();
      await refreshWorkspace();
    },
  });

  // Moving to another customer loads it and opens it in the menu.
  $effect(() => {
    const wanted = Number(id);
    // Only the ID counts: what loading reads (the customer so far, the menu's
    // list) mustn't start it again.
    untrack(() => {
      leaving = false;
      void chooseCustomer(wanted);
      void load();
    });
  });
</script>

<main class="page-content">
  {#if error}
    <div>
      <a class="small" href={resolve("/(app)/customers")}>All customers</a>
      <p class="alert alert-critical" role="alert">{error}</p>
    </div>
  {:else if customer}
    <RecordHeader kind="Customer" title={customer.name} icon={Building} image={customer.logo_url}>
      {#if customer.visibility === "full" && customer.cvr}
        <p class="small muted">CVR <span class="mono">{formatCvr(customer.cvr)}</span></p>
      {/if}
    </RecordHeader>

    {#if customer.visibility === "full"}
      {@render children()}
    {:else}
      <section class="section">
        <h2 class="section-title">Overview only</h2>
        <p class="muted">
          Auditors see that every customer exists, for the audit log. Its details, contacts and
          records are for Administrators and the technicians assigned to it.
        </p>
      </section>
    {/if}
  {/if}
</main>
