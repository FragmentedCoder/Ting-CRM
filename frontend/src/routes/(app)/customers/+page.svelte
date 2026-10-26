<script lang="ts">
  import { resolve } from "$app/paths";
  import Plus from "@lucide/svelte/icons/plus";
  import Search from "@lucide/svelte/icons/search";
  import { onMount } from "svelte";
  import { api, ApiError, sessionGone } from "#lib/api.js";
  import { pageTitle } from "#lib/branding.svelte.js";
  import Pill from "#lib/components/Pill.svelte";
  import { formatCvr, type CustomerSummary } from "#lib/customers.js";
  import { can, session } from "#lib/session.svelte.js";

  const info = $derived(session.current);
  let customers = $state<CustomerSummary[] | null>(null);
  let query = $state("");
  let error = $state<string | null>(null);
  let searchTimer: ReturnType<typeof setTimeout> | undefined;

  const mayAdd = $derived(can(info, "manage_customers"));
  const limited = $derived(customers?.some((c) => c.visibility !== "full") ?? false);

  async function load() {
    try {
      customers = await api<CustomerSummary[]>("GET", `/customers?q=${encodeURIComponent(query)}`);
      error = null;
    } catch (e) {
      if (!sessionGone(e)) error = e instanceof ApiError ? e.message : "The customers could not be loaded.";
    }
  }

  // Searches as you type, once you pause.
  function search() {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(load, 250);
  }

  onMount(load);
</script>

<svelte:head><title>{pageTitle("Customers")}</title></svelte:head>

<main class="page-content">
  <div class="page-header">
    <div>
      <h1 class="title">Customers</h1>
      <p class="small muted">
        {#if mayAdd}
          Every customer. Each has its own encryption key, and technicians see only the
          customers they're assigned to.
        {:else if can(info, "edit_customers")}
          The customers you work with. An administrator assigns you to customers.
        {:else}
          Every customer, as an overview for the audit log.
        {/if}
      </p>
    </div>
    {#if mayAdd}
      <a class="button button-primary" href={resolve("/(app)/customers/new")}>
        <Plus size={18} aria-hidden="true" />
        Add customer
      </a>
    {/if}
  </div>

  <div class="field search">
    <label for="customer-search" class="visually-hidden">Search customers</label>
    <Search class="search-icon" size={16} aria-hidden="true" />
    <input id="customer-search" class="input" type="search" placeholder="Search by name or CVR"
      bind:value={query} oninput={search} />
  </div>

  {#if error}<p class="alert alert-critical" role="alert">{error}</p>{/if}

  {#if customers}
    {#if customers.length}
      <div class="section table-wrap customers">
        <table class="table">
          <thead>
            <tr><th>Name</th><th class="roomy">CVR</th><th>People</th></tr>
          </thead>
          <tbody>
            {#each customers as customer (customer.id)}
              <tr>
                <td>
                  <a class="row-link" href={resolve("/(app)/customers/[id]", { id: String(customer.id) })}>
                    {customer.name}
                  </a>
                  {#if customer.visibility !== "full"}
                    <Pill tone="neutral" text="Overview only" />
                  {/if}
                </td>
                <td class="roomy mono">{customer.visibility === "full" ? formatCvr(customer.cvr) : "—"}</td>
                <td>{customer.people ?? "—"}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
      {#if limited}
        <p class="small muted">
          Your role shows customers as an overview only: enough to audit, without their
          details or contacts.
        </p>
      {/if}
    {:else}
      <section class="empty">
        <p>{query ? "No customer matches that." : "No customers yet."}</p>
        <p class="small muted">
          {#if query}
            Try part of the name, or the CVR number.
          {:else if mayAdd}
            Add the first one, with its sites and contacts.
          {:else}
            An administrator assigns you to the customers you work with.
          {/if}
        </p>
      </section>
    {/if}
  {/if}
</main>

<style>
  /* Where the table is narrow, as on a phone, the CVR number goes. */
  .customers {
    container-type: inline-size;
  }
  @container (max-width: 520px) {
    .roomy {
      display: none;
    }
  }
  .search {
    position: relative;
    max-width: 420px;
  }
  .search :global(.search-icon) {
    position: absolute;
    top: 50%;
    left: 12px;
    color: var(--text-muted);
    transform: translateY(-50%);
  }
  .search .input {
    padding-left: 36px;
  }
  .empty {
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
    padding: var(--space-8);
    border: 1px dashed var(--border-strong);
    border-radius: var(--radius-lg);
    text-align: center;
  }
</style>
