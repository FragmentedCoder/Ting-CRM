<script lang="ts">
  import { resolve } from "$app/paths";
  import { branding } from "#lib/branding.svelte.js";
  import { formatCvr } from "#lib/customers.js";
  import { roleName } from "#lib/roles.js";
  import { can, session } from "#lib/session.svelte.js";
  import { workspace } from "#lib/workspace.svelte.js";

  // Where the day starts: the customers you work with. Tasks, notice deadlines and
  // renewals join them once Þing keeps agreements.
  const info = $derived(session.current);
  const customers = $derived(workspace.customers?.filter((c) => c.visibility === "full") ?? null);
  const shown = $derived(customers?.slice(0, 8) ?? []);
</script>

<svelte:head><title>{branding.current.site_name}</title></svelte:head>

{#if info}
  <main class="page-content">
    <div class="heading">
      <h1 class="title">Welcome, {info.user.display_name}</h1>
      {#if info.user.roles.length}
        <p class="small muted">{info.user.roles.map(roleName).join(", ")}</p>
      {/if}
    </div>

    {#if customers?.length}
      <section class="section" aria-labelledby="customers-title">
        <h2 class="section-title" id="customers-title">
          {can(info, "manage_customers") ? "Customers" : "Your customers"}
        </h2>
        <ul class="customers">
          {#each shown as customer (customer.id)}
            <li>
              <a href={resolve("/(app)/customers/[id]", { id: String(customer.id) })}>{customer.name}</a>
              {#if customer.cvr}<span class="small muted mono">{formatCvr(customer.cvr)}</span>{/if}
            </li>
          {/each}
        </ul>
        {#if customers.length > shown.length}
          <a class="small" href={resolve("/(app)/customers")}>All {customers.length} customers</a>
        {/if}
      </section>
    {:else if customers}
      <section class="empty">
        <p>No customers yet.</p>
        <p class="small muted">
          {#if can(info, "manage_customers")}
            Add a customer, with its contacts and sites, and assign technicians to it.
          {:else if can(info, "edit_customers")}
            An administrator assigns you to the customers you work with.
          {:else if info.user.roles.length}
            There's nothing here for your role.
          {:else}
            You don't have a role yet. Ask an administrator for one.
          {/if}
        </p>
      </section>
    {/if}
  </main>
{/if}

<style>
  .heading {
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
  }
  .customers {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    margin: 0;
    padding: 0;
    list-style: none;
  }
  .customers li {
    display: flex;
    flex-wrap: wrap;
    align-items: baseline;
    gap: var(--space-2);
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
