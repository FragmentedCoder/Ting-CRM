<script lang="ts">
  import Pencil from "@lucide/svelte/icons/pencil";
  import Plus from "@lucide/svelte/icons/plus";
  import Trash from "@lucide/svelte/icons/trash-2";
  import { api, ApiError, sessionGone } from "#lib/api.js";
  import { pageTitle } from "#lib/branding.svelte.js";
  import Dialog from "#lib/components/Dialog.svelte";
  import RowMenu from "#lib/components/RowMenu.svelte";
  import { sharedCustomer } from "#lib/context.js";
  import ContactCard from "#lib/components/ContactCard.svelte";
  import PhoneField from "#lib/components/PhoneField.svelte";
  import Pill from "#lib/components/Pill.svelte";
  import {
    CONTACT_ROLES, SITE_KINDS, emptyContact, emptySite,
    type Contact, type CustomerDetail, type Site,
  } from "#lib/customers.js";
  import { toast } from "#lib/toast.svelte.js";

  // The customer's people and places, as in the mockup: contacts for the whole company,
  // then a card per site with its own contact, opening hours, access and parking.
  // Administrators, Managers and technicians who may see the customer change them.
  const shared = sharedCustomer();
  const customer = $derived(shared.current);
  const contacts = $derived(customer?.contacts ?? []);
  const whole = $derived(contacts.filter((c) => c.site_id === null));
  const byId = $derived(new Map(contacts.map((c) => [c.id, c])));
  const alsoAt = (place: Site) =>
    contacts.filter((c) => c.site_id === place.id && c.id !== place.contact_id).map((c) => c.name);
  const base = $derived(`/customers/${customer?.id}`);

  let site = $state<(Omit<Site, "id"> & { id: number | null }) | null>(null);
  let contact = $state<(Omit<Contact, "id"> & { id: number | null }) | null>(null);
  let siteOpen = $state(false);
  let contactOpen = $state(false);
  let removing = $state<{ kind: "sites" | "contacts"; id: number; name: string } | null>(null);
  let removeOpen = $state(false);
  let error = $state<string | null>(null);
  let busy = $state(false);

  function editSite(found?: Site) {
    site = found ? { ...found } : { id: null, ...emptySite() };
    error = null;
    siteOpen = true;
  }

  function editContact(found?: Contact) {
    contact = found ? { ...found, roles: [...found.roles] } : { id: null, ...emptyContact() };
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

<svelte:head><title>{pageTitle(`Contacts and sites · ${customer?.name ?? "Customer"}`)}</title></svelte:head>

{#snippet contactActions(item: Contact)}
  {#if customer?.may_edit}
    <RowMenu label="Actions for {item.name}" items={[
      { label: "Change contact", icon: Pencil, run: () => editContact(item) },
      { label: "Remove contact", icon: Trash, danger: true, run: () => askToRemove("contacts", item.id, item.name) },
    ]} />
  {/if}
{/snippet}

{#if customer}
  <div class="heading-row">
    <p class="small muted">People at the customer and its places, encrypted with the customer's key.</p>
    {#if customer.may_edit}
      <div class="button-row">
        <button class="button button-primary" type="button" onclick={() => editSite()}>
          <Plus size={16} aria-hidden="true" />Add a site
        </button>
        <button class="button button-secondary" type="button" onclick={() => editContact()}>
          <Plus size={16} aria-hidden="true" />Add a contact
        </button>
      </div>
    {/if}
  </div>

  <section class="section" aria-labelledby="company-title">
    <h2 class="section-title" id="company-title">For the whole company</h2>
    {#if whole.length}
      <ul class="cards">
        {#each whole as item (item.id)}
          <li>
            <ContactCard contact={item}>
              {#snippet actions()}{@render contactActions(item)}{/snippet}
            </ContactCard>
          </li>
        {/each}
      </ul>
    {:else}
      <p class="muted">No contacts for the whole company yet.</p>
    {/if}
  </section>

  <section class="section" aria-labelledby="sites-title">
    <h2 class="section-title" id="sites-title">Sites</h2>
    {#if customer.sites?.length}
      <ul class="sites">
        {#each customer.sites as place (place.id)}
          {@const here = place.contact_id === null ? undefined : byId.get(place.contact_id)}
          {@const others = alsoAt(place)}
          <li class="site">
            <div class="site-head">
              <div class="site-name">
                <p class="check-title">{place.name}</p>
                <p class="small muted address">{place.address || "No address"}</p>
              </div>
              <Pill tone="neutral" text={SITE_KINDS[place.kind]} />
              {#if customer.may_edit}
                <RowMenu label="Actions for {place.name}" items={[
                  { label: "Change site", icon: Pencil, run: () => editSite(place) },
                  { label: "Remove site", icon: Trash, danger: true, run: () => askToRemove("sites", place.id, place.name) },
                ]} />
              {/if}
            </div>
            <div class="site-body">
              <p class="label">Contact at this site</p>
              {#if here}
                <ContactCard contact={here} inset>
                  {#snippet actions()}{@render contactActions(here)}{/snippet}
                </ContactCard>
              {:else}
                <p class="small muted none">No contact chosen yet.</p>
              {/if}
              {#if others.length}<p class="small muted">Also here: {others.join(", ")}</p>{/if}
              <dl class="rows">
                <dt>Opening hours</dt><dd>{place.opening_hours || "—"}</dd>
                <dt>Access</dt><dd class="two">{place.access || "—"}</dd>
                <dt>Parking</dt><dd class="two">{place.parking || "—"}</dd>
                <dt>Note</dt><dd class="two">{place.note || "—"}</dd>
              </dl>
            </div>
            {#if customer.may_edit}
              <div class="site-foot">
                <button class="button button-secondary small-button" type="button" onclick={() => editSite(place)}>
                  <Pencil size={14} aria-hidden="true" />Change site
                </button>
              </div>
            {/if}
          </li>
        {/each}
      </ul>
    {:else}
      <p class="muted">No sites yet.</p>
    {/if}
  </section>
{/if}

<Dialog bind:open={siteOpen} size="wide" title={site?.id ? "Change site" : "Add a site"}>
  {#if site}
    <form class="stack" onsubmit={saveSite}>
      {#if error}<p class="alert alert-critical" role="alert">{error}</p>{/if}
      <div class="field-grid">
        <div class="field">
          <label for="site-name">Name</label>
          <input id="site-name" class="input" required maxlength="150" placeholder="Head office" bind:value={site.name} />
        </div>
        <div class="field">
          <label for="site-kind">Type</label>
          <select id="site-kind" class="input" bind:value={site.kind}>
            {#each Object.entries(SITE_KINDS) as [value, name] (value)}<option {value}>{name}</option>{/each}
          </select>
        </div>
        <div class="field span-2">
          <label for="site-contact">Contact at this site</label>
          <select id="site-contact" class="input" bind:value={site.contact_id} required={contacts.length > 0}>
            <option value={null} disabled={contacts.length > 0}>{contacts.length ? "Choose a contact" : "Add a contact first"}</option>
            {#each contacts as item (item.id)}<option value={item.id}>{item.name}</option>{/each}
          </select>
          <span class="hint">Every site has its own contact; it may be the same person as at another site.</span>
        </div>
        <div class="field span-2 rows-2">
          <label for="site-address">Address</label>
          <textarea id="site-address" class="input" rows="3" maxlength="500" bind:value={site.address}></textarea>
        </div>
        <div class="field">
          <label for="site-hours">Opening hours</label>
          <input id="site-hours" class="input" maxlength="300" bind:value={site.opening_hours} />
        </div>
        <div class="field">
          <label for="site-parking">Parking</label>
          <input id="site-parking" class="input" maxlength="300" bind:value={site.parking} />
        </div>
        <div class="field span-2">
          <label for="site-access">Access</label>
          <input id="site-access" class="input" maxlength="500" bind:value={site.access} />
          <span class="hint">How to get in, such as “Key box by the gate”.</span>
        </div>
        <div class="field span-all">
          <label for="site-note">Note</label>
          <textarea id="site-note" class="input" rows="2" maxlength="1000" bind:value={site.note}></textarea>
        </div>
      </div>
      <div class="button-row end">
        <button class="button button-secondary" type="button" onclick={() => (siteOpen = false)}>Cancel</button>
        <button class="button button-primary" type="submit" disabled={busy}>Save site</button>
      </div>
    </form>
  {/if}
</Dialog>

<Dialog bind:open={contactOpen} size="wide" title={contact?.id ? "Change contact" : "Add a contact"}>
  {#if contact}
    <form class="stack" onsubmit={saveContact}>
      {#if error}<p class="alert alert-critical" role="alert">{error}</p>{/if}
      <div class="field-grid">
        <div class="field span-2">
          <label for="contact-name">Name</label>
          <input id="contact-name" class="input" required maxlength="200" bind:value={contact.name} />
        </div>
        <div class="field">
          <label for="contact-role">Title</label>
          <input id="contact-role" class="input" maxlength="150" placeholder="IT coordinator" bind:value={contact.role} />
        </div>
        <div class="field">
          <label for="contact-site">Site</label>
          <select id="contact-site" class="input" bind:value={contact.site_id}>
            <option value={null}>The whole company</option>
            {#each customer?.sites ?? [] as place (place.id)}<option value={place.id}>{place.name}</option>{/each}
          </select>
        </div>
        <div class="field span-2">
          <label for="contact-email">Email</label>
          <input id="contact-email" class="input" type="email" maxlength="254" bind:value={contact.email} />
        </div>
        <div class="field span-2">
          <label for="contact-phone">Phone</label>
          <PhoneField id="contact-phone" bind:value={contact.phone} />
        </div>
      </div>
      <fieldset class="checks across">
        <legend class="check-title">Roles</legend>
        {#each Object.entries(CONTACT_ROLES) as [value, name] (value)}
          <label class="check"><input type="checkbox" {value} bind:group={contact.roles} /><span>{name}</span></label>
        {/each}
      </fieldset>
      <fieldset class="checks">
        <legend class="check-title">Contacting them</legend>
        <div class="field-grid">
          <label class="check level">
            <input type="checkbox" bind:checked={contact.may_contact} />
            <span>May be contacted</span>
          </label>
          <div class="field">
            <label for="contact-channel">Preferred channel</label>
            <select id="contact-channel" class="input" bind:value={contact.preferred_channel}>
              <option value="">No preference</option><option value="phone">Phone</option><option value="email">Email</option>
            </select>
          </div>
          <div class="field span-2">
            <label for="contact-note">About contacting them</label>
            <input id="contact-note" class="input" maxlength="200" bind:value={contact.may_contact_note} />
            <span class="hint">Such as “Only about the server room”. Shown on their card.</span>
          </div>
        </div>
      </fieldset>
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
  .cards,
  .sites {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
    gap: var(--space-3);
    margin: 0;
    padding: 0;
    list-style: none;
  }
  .site {
    display: flex;
    flex-direction: column;
    overflow: hidden;
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
  }
  .site-head {
    display: flex;
    align-items: flex-start;
    gap: var(--space-2);
    min-height: 96px;
    box-sizing: border-box;
    padding: var(--space-4);
    border-bottom: 1px solid var(--border);
    background: var(--bg);
  }
  .site-name {
    flex: 1 1 auto;
    min-width: 0;
  }
  .site-body {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    padding: var(--space-4);
  }
  .label {
    margin: 0;
    color: var(--text-muted);
    font: var(--type-label);
  }
  .none {
    margin: 0;
    padding: var(--space-3) 0;
  }
  .rows {
    display: grid;
    grid-template-columns: 7.5rem minmax(0, 1fr);
    gap: 0 var(--space-3);
    margin: 0;
  }
  .rows dt,
  .rows dd {
    min-height: 2.75rem;
    margin: 0;
    padding: var(--space-2) 0;
    border-top: 1px solid var(--border);
    font: var(--type-body-sm);
  }
  .rows dt {
    color: var(--text-muted);
  }
  .two {
    display: -webkit-box;
    overflow: hidden;
    -webkit-box-orient: vertical;
    -webkit-line-clamp: 2;
    line-clamp: 2;
  }
  .site-foot {
    display: flex;
    justify-content: flex-end;
    margin-top: auto;
    padding: var(--space-2) var(--space-3) var(--space-3);
    border-top: 1px solid var(--border);
  }
  .small-button {
    min-height: 36px;
  }
  .address {
    margin: 0;
    white-space: pre-line;
  }
  .end {
    justify-content: flex-end;
  }
  /* The roles side by side, as many as fit on a line. */
  .across {
    flex-flow: row wrap;
    gap: var(--space-3) var(--space-6);
  }
  /* The tick box level with the boxes of the fields beside it. */
  .level {
    align-items: center;
    min-height: 46px;
    margin-top: var(--space-6);
  }
  @container dialog (max-width: 420px) {
    .level {
      margin-top: 0;
    }
  }
</style>
