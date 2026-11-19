<script lang="ts">
  import { resolve } from "$app/paths";
  import Plus from "@lucide/svelte/icons/plus";
  import Search from "@lucide/svelte/icons/search";
  import { onMount } from "svelte";
  import { api, ApiError, sessionGone } from "#lib/api.js";
  import { pageTitle } from "#lib/branding.svelte.js";
  import FilterChips from "#lib/components/FilterChips.svelte";
  import Pill from "#lib/components/Pill.svelte";
  import { customerFilters, formatCvr, statusPill, type CustomerFilter, type CustomerSummary } from "#lib/customers.js";
  import { reasonWords, servicesWords, type CustomerStanding } from "#lib/mywork.js";
  import { today } from "#lib/planning.js";
  import { can, session } from "#lib/session.svelte.js";

  // All customers: every customer someone may see, found by name, CVR number or
  // town, and narrowed to theirs, to those needing attention, or by status. Those who
  // work with customers also see each one's services and what needs attention.
  const info = $derived(session.current);
  let customers = $state<CustomerSummary[] | null>(null);
  let query = $state("");
  let filter = $state<CustomerFilter>("all");
  let error = $state<string | null>(null);
  let searchTimer: ReturnType<typeof setTimeout> | undefined;

  const mayAdd = $derived(can(info, "manage_customers"));
  const works = $derived(can(info, "edit_customers"));
  const now = today();
  let standing = $state<Record<number, CustomerStanding> | null>(null);
  const needing = $derived(Object.values(standing ?? {}).filter((s) => s.reasons.length).map((s) => s.customer_id));
  const overviewOnly = $derived(customers?.some((c) => c.visibility !== "full") ?? false);
  const filters = $derived(customerFilters(customers ?? [], needing));
  const shown = $derived(filters.find((f) => f.value === filter)?.customers ?? []);

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

  // Services and attention come once, beside the list: they don't change as you type.
  $effect(() => {
    if (!works) return;
    api<CustomerStanding[]>("GET", "/attention")
      .then((rows) => (standing = Object.fromEntries(rows.map((row) => [row.customer_id, row]))))
      .catch(() => (standing = null));
  });
</script>

<svelte:head><title>{pageTitle("All customers")}</title></svelte:head>

<main class="page-content">
  <div class="page-header">
    <div>
      <h1 class="title">All customers</h1>
      <p class="small muted">
        {#if customers}
          {customers.length === 1 ? "1 customer" : `${customers.length} customers`}{query ? " found" : ""} ·
        {/if}
        {#if mayAdd}
          each with its own encryption key. Technicians see every one, unless an Administrator
          limits them to the customers they're assigned to.
        {:else if can(info, "edit_customers")}
          open one to see its overview.
        {:else}
          an overview for the audit log.
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

  <div class="section filters">
    <div class="field search">
      <label for="customer-search" class="visually-hidden">Search customers</label>
      <Search class="search-icon" size={16} aria-hidden="true" />
      <input id="customer-search" class="input" type="search" placeholder="Name, CVR number or town"
        bind:value={query} oninput={search} />
    </div>
    {#if customers && !overviewOnly}
      <FilterChips label="Show" bind:value={filter}
        options={filters.map((f) => ({ value: f.value, label: f.label, count: f.customers.length }))} />
    {/if}
  </div>

  {#if error}<p class="alert alert-critical" role="alert">{error}</p>{/if}

  {#if customers}
    {#if shown.length}
      <div class="section table-wrap customers">
        <table class="table">
          <thead>
            <tr>
              <th>Customer</th><th>Status</th>
              {#if standing}<th class="roomy">Services</th>{/if}
              <th class="roomy">Usually worked on by</th>
              {#if standing}<th>Needs attention</th>{/if}
            </tr>
          </thead>
          <tbody>
            {#each shown as customer (customer.id)}
              <tr class:former={customer.status === "former"}>
                <td>
                  <a class="row-link name" href={resolve("/(app)/customers/[id]", { id: String(customer.id) })}>
                    {customer.name}
                  </a>
                  {#if customer.visibility === "full"}
                    <span class="small muted mono where">
                      {[customer.cvr ? `CVR ${formatCvr(customer.cvr)}` : null, customer.town].filter(Boolean).join(" · ") || "No CVR number"}
                    </span>
                  {/if}
                </td>
                <td>
                  {#if customer.visibility !== "full"}
                    <Pill tone="neutral" text="Overview only" />
                  {:else if customer.status}
                    <Pill {...statusPill(customer.status)} />
                  {/if}
                </td>
                {#if standing}
                  {@const services = standing[customer.id] ? servicesWords(standing[customer.id]) : null}
                  <td class="roomy">
                    {#if services}
                      <span class:muted={!standing[customer.id].services}>{services.count}</span>
                      {#if services.uncovered}<span class="small uncovered">· {services.uncovered}</span>{/if}
                    {:else}
                      —
                    {/if}
                  </td>
                {/if}
                <td class="roomy">
                  {#if customer.visibility !== "full"}
                    —
                  {:else if customer.worked_on_by?.length}
                    {customer.worked_on_by.join(", ")}
                  {:else}
                    <span class="muted">Nobody yet</span>
                  {/if}
                </td>
                {#if standing}
                  {@const needs = standing[customer.id]}
                  <td>
                    {#if needs?.reasons.length}
                      <span class="reasons">
                        {#each needs.reasons as reason (reason.kind)}<Pill tone={reason.tone} text={reasonWords(reason, now)} />{/each}
                        {#if needs.more}<span class="small muted">and {needs.more} more</span>{/if}
                      </span>
                    {:else if needs}
                      <span class="muted">Nothing</span>
                    {:else}
                      —
                    {/if}
                  </td>
                {/if}
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
      {#if overviewOnly}
        <p class="small muted">
          Your role shows customers as an overview only: enough to audit, without their
          details or contacts.
        </p>
      {/if}
    {:else}
      <section class="empty">
        {#if customers.length}
          <p>No customer here.</p>
          <p class="small muted">Choose another filter above.</p>
        {:else}
          <p>{query ? "No customer matches that." : "No customers yet."}</p>
          <p class="small muted">
            {#if query}
              Try part of the name, the CVR number or the town.
            {:else if mayAdd}
              Add the first one, with its sites and contacts.
            {:else}
              A Manager adds customers.
            {/if}
          </p>
        {/if}
      </section>
    {/if}
  {/if}
</main>

<style>
  /* Where the table is narrow, as on a phone, who works on it goes. */
  .customers {
    container-type: inline-size;
  }
  @container (max-width: 520px) {
    .roomy {
      display: none;
    }
  }
  /* The search and the chips side by side: a section stacks its parts unless told. */
  .filters {
    display: flex;
    flex-flow: row wrap;
    gap: var(--space-3);
    align-items: center;
  }
  .search {
    position: relative;
    flex: 1 1 260px;
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
  .name,
  .where {
    display: block;
  }
  /* Up to three badges, one under the other, most urgent first. */
  .reasons {
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    gap: var(--space-1);
  }
  .uncovered {
    color: var(--warning-text);
    white-space: nowrap;
  }
  .name {
    font-weight: 600;
  }
  .former td,
  .former .name {
    color: var(--text-muted);
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
