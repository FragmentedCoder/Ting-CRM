<script lang="ts">
  import Search from "@lucide/svelte/icons/search";
  import { api, ApiError, sessionGone } from "#lib/api.js";
  import { pageTitle } from "#lib/branding.svelte.js";
  import Avatar from "#lib/components/Avatar.svelte";
  import Pill from "#lib/components/Pill.svelte";
  import { sharedCustomer } from "#lib/context.js";
  import { findPeople, otherCustomers, samePeople, type CustomerDetail } from "#lib/customers.js";
  import { roleName } from "#lib/roles.js";
  import { toast } from "#lib/toast.svelte.js";

  // The technicians who work with the customer. Administrators and Managers choose,
  // among every technician: a tile each, with their picture, what else they have
  // and whether they see only the customers they're assigned to. Everyone who sees
  // the customer sees who.
  const shared = sharedCustomer();
  const customer = $derived(shared.current);
  const people = $derived(customer?.assignable ?? []);
  const assigned = $derived((customer?.assigned ?? []).map((p) => p.id));
  // Start from who's assigned now; the tiles change them until they're saved.
  let chosen = $derived([...assigned]);
  const changed = $derived(!samePeople(chosen, assigned));
  let busy = $state(false);

  // A long team gets a box to find someone in.
  const FIND_FROM = 9;
  let words = $state("");
  const shown = $derived(findPeople(people, words));

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
    <div class="heading-row">
      <h2 class="section-title" id="people-title">Who works with this customer</h2>
      {#if customer.may_manage && people.length}
        <p class="count" aria-live="polite">
          <span class="number">{chosen.length}</span> of {people.length} {people.length === 1 ? "technician" : "technicians"} chosen
        </p>
      {/if}
    </div>
    <p class="small muted">
      The technicians who usually work with this customer: its work shows up on their My work.
      Every technician sees every customer, unless an Administrator limits them to the customers
      they're assigned to.
    </p>
    {#if customer.may_manage}
      {#if people.length}
        <form class="stack" onsubmit={save}>
          {#if people.length >= FIND_FROM}
            <div class="find">
              <Search size={16} aria-hidden="true" />
              <input class="input" type="search" aria-label="Find a technician" placeholder="Find a technician"
                autocomplete="off" bind:value={words} />
            </div>
          {/if}
          <fieldset class="tiles">
            <legend class="visually-hidden">Technicians</legend>
            {#each shown as person (person.id)}
              <label class="person choose">
                <Avatar name={person.display_name} url={person.avatar_url} size={40} />
                <span class="who">
                  <span class="check-title">{person.display_name}</span>
                  <span class="small">{person.roles.map(roleName).join(", ")}</span>
                  <span class="small muted mono">{person.username}</span>
                  <span class="small muted">{otherCustomers(person, assigned.includes(person.id))}</span>
                  {#if person.limited}
                    <span class="limit"><Pill tone="neutral" text="Sees only assigned customers" /></span>
                  {/if}
                </span>
                <input class="tick" type="checkbox" value={person.id} bind:group={chosen} />
              </label>
            {/each}
          </fieldset>
          {#if !shown.length}<p class="muted">Nobody's name has “{words.trim()}” in it.</p>{/if}
          <div class="button-row">
            <button class="button button-primary" type="submit" disabled={busy || !changed}>Save</button>
            {#if changed}
              <button class="button button-secondary" type="button" disabled={busy}
                onclick={() => (chosen = [...assigned])}>Undo changes</button>
            {/if}
          </div>
        </form>
      {:else}
        <p class="muted">
          Nobody has the Technician role yet. Give someone it in Admin → Users, then assign them
          here.
        </p>
      {/if}
    {:else if customer.assigned?.length}
      <ul class="tiles">
        {#each customer.assigned as person (person.id)}
          <li class="person">
            <Avatar name={person.display_name} url={person.avatar_url} size={40} />
            <span class="who">
              <span class="check-title">{person.display_name}</span>
              <span class="small">{person.roles.map(roleName).join(", ")}</span>
            </span>
          </li>
        {/each}
      </ul>
    {:else}
      <p class="muted">Nobody is assigned yet.</p>
    {/if}
  </section>
{/if}

<style>
  .heading-row {
    display: flex;
    flex-wrap: wrap;
    align-items: baseline;
    justify-content: space-between;
    gap: var(--space-2) var(--space-4);
  }
  .count {
    color: var(--text-muted);
    font: var(--type-body-sm);
  }
  .number {
    color: var(--text);
    font: var(--type-label);
  }
  .find {
    position: relative;
    max-width: 320px;
    color: var(--text-muted);
  }
  .find :global(svg) {
    position: absolute;
    top: 14px;
    left: 12px;
    pointer-events: none;
  }
  .find .input {
    padding-left: 36px;
  }
  .tiles {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
    gap: var(--space-3);
    min-width: 0;
    margin: 0;
    padding: 0;
    border: 0;
    list-style: none;
  }
  .person {
    display: flex;
    align-items: center;
    gap: var(--space-3);
    min-width: 0;
    padding: var(--space-3) var(--space-4);
    border: 1px solid var(--border);
    border-radius: var(--radius-md);
    background: var(--bg);
  }
  .who {
    display: flex;
    flex: 1 1 auto;
    flex-direction: column;
    min-width: 0;
  }
  .who > span {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .limit {
    margin-top: var(--space-1);
  }
  /* A tile to choose: the whole of it is the tick box's label. Chosen, it takes the
     colour the tick has. */
  .choose {
    cursor: pointer;
  }
  .choose:hover {
    border-color: var(--border-strong);
  }
  .choose:has(.tick:checked) {
    border-color: var(--link);
    background: color-mix(in srgb, var(--link) 9%, var(--surface));
    box-shadow: inset 0 0 0 1px var(--link);
  }
  .choose:has(.tick:focus-visible) {
    outline: 2px solid var(--link);
    outline-offset: 2px;
  }
  /* The tick box itself, drawn as a round mark: a ring, filled with a tick when
     chosen. Still a checkbox to the keyboard and to a screen reader. */
  .tick {
    display: grid;
    flex: none;
    place-items: center;
    width: 24px;
    height: 24px;
    margin: 0;
    border: 2px solid var(--border-strong);
    border-radius: 50%;
    background: var(--surface);
    appearance: none;
    cursor: pointer;
  }
  .tick:focus-visible {
    outline: none;
  }
  .tick:checked {
    border-color: var(--link);
    background: var(--link);
  }
  .tick:checked::after {
    width: 6px;
    height: 11px;
    margin-top: -2px;
    border: solid var(--surface);
    border-width: 0 2px 2px 0;
    content: "";
    transform: rotate(45deg);
  }
</style>
