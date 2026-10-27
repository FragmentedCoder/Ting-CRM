<script lang="ts">
  import { api, ApiError, sessionGone } from "#lib/api.js";
  import { pageTitle } from "#lib/branding.svelte.js";
  import { sharedCustomer } from "#lib/context.js";
  import type { CustomerDetail } from "#lib/customers.js";
  import { toast } from "#lib/toast.svelte.js";

  // The technicians who work with the customer. Administrators choose; everyone who
  // sees the customer sees who.
  const shared = sharedCustomer();
  const customer = $derived(shared.current);
  // Start from who's assigned now; the checkboxes change them until they're saved.
  let chosen = $derived((customer?.assigned ?? []).map((p) => p.id));
  let busy = $state(false);

  async function save(event: SubmitEvent) {
    event.preventDefault();
    busy = true;
    try {
      shared.use(await api<CustomerDetail>("PUT", `/customers/${customer?.id}/assignments`,
        { people: chosen }));
      toast("Who works with this customer is saved.", "ok", { key: "saved" });
    } catch (e) {
      if (!sessionGone(e)) toast(e instanceof ApiError ? e.message : "Something went wrong.", "critical");
    } finally {
      busy = false;
    }
  }
</script>

<svelte:head><title>{pageTitle(`People · ${customer?.name ?? "Customer"}`)}</title></svelte:head>

{#if customer}
  <section class="section" aria-labelledby="people-title">
    <h2 class="section-title" id="people-title">Who works with this customer</h2>
    <p class="small muted">
      Technicians see only the customers they're assigned to, and read and update their records.
      Administrators see every customer.
    </p>
    {#if customer.may_manage}
      <form class="stack" onsubmit={save}>
        {#if customer.assignable?.length}
          <fieldset class="checks">
            <legend class="visually-hidden">Technicians</legend>
            {#each customer.assignable as person (person.id)}
              <label class="check">
                <input type="checkbox" value={person.id} bind:group={chosen} />
                <span>
                  <span class="check-title">{person.display_name}</span>
                  <span class="small muted mono">{person.username}</span>
                </span>
              </label>
            {/each}
          </fieldset>
          <div><button class="button button-primary" type="submit" disabled={busy}>Save</button></div>
        {:else}
          <p class="muted">
            Nobody has the Technician role yet. Give someone it in Admin → Users, then assign them
            here.
          </p>
        {/if}
      </form>
    {:else if customer.assigned?.length}
      <ul class="people">
        {#each customer.assigned as person (person.id)}
          <li class="check-title">{person.display_name}</li>
        {/each}
      </ul>
    {:else}
      <p class="muted">Nobody is assigned yet.</p>
    {/if}
  </section>
{/if}

<style>
  .people {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    margin: 0;
    padding: 0;
    list-style: none;
  }
</style>
