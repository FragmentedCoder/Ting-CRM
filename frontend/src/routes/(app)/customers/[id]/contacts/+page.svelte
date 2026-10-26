<script lang="ts">
  import Pencil from "@lucide/svelte/icons/pencil";
  import Plus from "@lucide/svelte/icons/plus";
  import Trash from "@lucide/svelte/icons/trash-2";
  import { api, ApiError, sessionGone } from "#lib/api.js";
  import { pageTitle } from "#lib/branding.svelte.js";
  import Dialog from "#lib/components/Dialog.svelte";
  import RowMenu from "#lib/components/RowMenu.svelte";
  import { sharedCustomer } from "#lib/context.js";
  import type { Contact, CustomerDetail, Site } from "#lib/customers.js";
  import { toast } from "#lib/toast.svelte.js";

  // The customer's people and places. Administrators and the technicians assigned to
  // the customer change them.
  const shared = sharedCustomer();
  const customer = $derived(shared.current);
  const base = $derived(`/customers/${customer?.id}`);

  let site = $state<{ id: number | null; name: string; address: string } | null>(null);
  let contact = $state<(Omit<Contact, "id"> & { id: number | null }) | null>(null);
  let siteOpen = $state(false);
  let contactOpen = $state(false);
  let removing = $state<{ kind: "sites" | "contacts"; id: number; name: string } | null>(null);
  let removeOpen = $state(false);
  let error = $state<string | null>(null);
  let busy = $state(false);

  function editSite(found?: Site) {
    site = found ? { ...found } : { id: null, name: "", address: "" };
    error = null;
    siteOpen = true;
  }

  function editContact(found?: Contact) {
    contact = found ? { ...found } : { id: null, name: "", role: "", email: "", phone: "" };
    error = null;
    contactOpen = true;
  }

  async function run(action: () => Promise<CustomerDetail>, done: string, close?: () => void) {
    busy = true;
    error = null;
    try {
      shared.use(await action());
      close?.();
      toast(done, "ok", { key: "saved" });
    } catch (e) {
      if (sessionGone(e)) return;
      const message = e instanceof ApiError ? e.message : "Something went wrong. Try again.";
      if (close) error = message;
      else toast(message, "critical");
    } finally {
      busy = false;
    }
  }

  function saveSite(event: SubmitEvent) {
    event.preventDefault();
    if (!site) return;
    const { id: siteId, ...body } = site;
    run(() => siteId === null
      ? api("POST", `${base}/sites`, body)
      : api("PUT", `${base}/sites/${siteId}`, body), "Site saved.", () => (siteOpen = false));
  }

  function saveContact(event: SubmitEvent) {
    event.preventDefault();
    if (!contact) return;
    const { id: contactId, ...body } = contact;
    run(() => contactId === null
      ? api("POST", `${base}/contacts`, body)
      : api("PUT", `${base}/contacts/${contactId}`, body), "Contact saved.",
    () => (contactOpen = false));
  }

  function askToRemove(kind: "sites" | "contacts", itemId: number, name: string) {
    removing = { kind, id: itemId, name };
    removeOpen = true;
  }

  function remove() {
    const chosen = removing;
    removeOpen = false;
    if (chosen) run(() => api("DELETE", `${base}/${chosen.kind}/${chosen.id}`), `${chosen.name} is removed.`);
  }
</script>

<svelte:head><title>{pageTitle(`Contacts & sites · ${customer?.name ?? "Customer"}`)}</title></svelte:head>

{#if customer}
  <section class="section" aria-labelledby="contacts-title">
    <div class="heading-row">
      <h2 class="section-title" id="contacts-title">Contacts</h2>
      {#if customer.may_edit}
        <button class="button button-secondary" type="button" onclick={() => editContact()}>
          <Plus size={16} aria-hidden="true" />Add contact
        </button>
      {/if}
    </div>
    <p class="small muted">
      People at the customer. Encrypted with the customer's key.
    </p>
    {#if customer.contacts?.length}
      <ul class="cards">
        {#each customer.contacts as item (item.id)}
          <li>
            <div class="card-head">
              <p class="check-title">{item.name}</p>
              {#if customer.may_edit}
                <RowMenu label="Actions for {item.name}" items={[
                  { label: "Change contact", icon: Pencil, run: () => editContact(item) },
                  { label: "Remove contact", icon: Trash, danger: true,
                    run: () => askToRemove("contacts", item.id, item.name) },
                ]} />
              {/if}
            </div>
            {#if item.role}<p class="small">{item.role}</p>{/if}
            {#if item.email}
              <!-- eslint-disable-next-line svelte/no-navigation-without-resolve -- an email address, not a page -->
              <a class="small" href="mailto:{item.email}">{item.email}</a>
            {/if}
            {#if item.phone}
              <!-- eslint-disable-next-line svelte/no-navigation-without-resolve -- a phone number, not a page -->
              <a class="small" href="tel:{item.phone.replace(/[^0-9+]/g, '')}">{item.phone}</a>
            {/if}
            {#if !item.email && !item.phone}<p class="small muted">No email or phone</p>{/if}
          </li>
        {/each}
      </ul>
    {:else}
      <p class="muted">No contacts yet.</p>
    {/if}
  </section>

  <section class="section" aria-labelledby="sites-title">
    <div class="heading-row">
      <h2 class="section-title" id="sites-title">Sites</h2>
      {#if customer.may_edit}
        <button class="button button-secondary" type="button" onclick={() => editSite()}>
          <Plus size={16} aria-hidden="true" />Add site
        </button>
      {/if}
    </div>
    <p class="small muted">The customer's locations.</p>
    {#if customer.sites?.length}
      <ul class="cards">
        {#each customer.sites as item (item.id)}
          <li>
            <div class="card-head">
              <p class="check-title">{item.name}</p>
              {#if customer.may_edit}
                <RowMenu label="Actions for {item.name}" items={[
                  { label: "Change site", icon: Pencil, run: () => editSite(item) },
                  { label: "Remove site", icon: Trash, danger: true,
                    run: () => askToRemove("sites", item.id, item.name) },
                ]} />
              {/if}
            </div>
            <p class="small muted address">{item.address || "No address"}</p>
          </li>
        {/each}
      </ul>
    {:else}
      <p class="muted">No sites yet.</p>
    {/if}
  </section>
{/if}

<Dialog bind:open={siteOpen} title={site?.id ? "Change site" : "Add site"}>
  {#if site}
    <form class="stack" onsubmit={saveSite}>
      {#if error}<p class="alert alert-critical" role="alert">{error}</p>{/if}
      <div class="field">
        <label for="site-name">Name</label>
        <input id="site-name" class="input" required maxlength="150" bind:value={site.name} />
        <span class="hint">Such as “Head office” or “Datacentre Aarhus”.</span>
      </div>
      <div class="field">
        <label for="site-address">Address</label>
        <textarea id="site-address" class="input" rows="3" maxlength="500" bind:value={site.address}></textarea>
      </div>
      <div class="button-row end">
        <button class="button button-secondary" type="button" onclick={() => (siteOpen = false)}>Cancel</button>
        <button class="button button-primary" type="submit" disabled={busy}>Save site</button>
      </div>
    </form>
  {/if}
</Dialog>

<Dialog bind:open={contactOpen} title={contact?.id ? "Change contact" : "Add contact"}>
  {#if contact}
    <form class="stack" onsubmit={saveContact}>
      {#if error}<p class="alert alert-critical" role="alert">{error}</p>{/if}
      <div class="field">
        <label for="contact-name">Name</label>
        <input id="contact-name" class="input" required maxlength="200" bind:value={contact.name} />
      </div>
      <div class="field">
        <label for="contact-role">Role</label>
        <input id="contact-role" class="input" maxlength="150" bind:value={contact.role} />
        <span class="hint">Such as “IT manager”.</span>
      </div>
      <div class="field">
        <label for="contact-email">Email</label>
        <input id="contact-email" class="input" type="email" maxlength="254" bind:value={contact.email} />
      </div>
      <div class="field">
        <label for="contact-phone">Phone</label>
        <input id="contact-phone" class="input" type="tel" maxlength="50" bind:value={contact.phone} />
      </div>
      <div class="button-row end">
        <button class="button button-secondary" type="button" onclick={() => (contactOpen = false)}>Cancel</button>
        <button class="button button-primary" type="submit" disabled={busy}>Save contact</button>
      </div>
    </form>
  {/if}
</Dialog>

<Dialog bind:open={removeOpen} title="Remove {removing?.name ?? ''}">
  <p>
    {#if removing?.kind === "contacts"}
      The contact is removed from this customer, and the change is logged.
    {:else}
      The site is removed from this customer, and the change is logged.
    {/if}
  </p>
  {#snippet actions()}
    <button class="button button-secondary" type="button" onclick={() => (removeOpen = false)}>Cancel</button>
    <button class="button button-primary" type="button" disabled={busy} onclick={remove}>
      Remove {removing?.kind === "contacts" ? "contact" : "site"}
    </button>
  {/snippet}
</Dialog>

<style>
  .heading-row {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-3);
  }
  .cards {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
    gap: var(--space-3);
    margin: 0;
    padding: 0;
    list-style: none;
  }
  .cards li {
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
    padding: var(--space-3) var(--space-4);
    border: 1px solid var(--border);
    border-radius: var(--radius-md);
  }
  /* The ⋮ button sits in the corner without making the first line taller. */
  .card-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-2);
    margin: calc(-1 * var(--space-2)) calc(-1 * var(--space-2)) calc(-1 * var(--space-1)) 0;
  }
  .address {
    white-space: pre-line;
  }
  .end {
    justify-content: flex-end;
  }
</style>
