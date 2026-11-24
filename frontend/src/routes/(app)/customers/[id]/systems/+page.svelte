<script lang="ts">
  import { page } from "$app/state";
  import { resolve } from "$app/paths";
  import Pencil from "@lucide/svelte/icons/pencil";
  import Plus from "@lucide/svelte/icons/plus";
  import Trash from "@lucide/svelte/icons/trash-2";
  import { api, ApiError, sessionGone } from "#lib/api.js";
  import { pageTitle } from "#lib/branding.svelte.js";
  import ContactCard from "#lib/components/ContactCard.svelte";
  import Dialog from "#lib/components/Dialog.svelte";
  import Pill from "#lib/components/Pill.svelte";
  import RowMenu from "#lib/components/RowMenu.svelte";
  import SideList from "#lib/components/SideList.svelte";
  import { sharedCustomer } from "#lib/context.js";
  import {
    SYSTEM_GROUPS, SYSTEM_TYPES, emptySystem, systemGroups,
    type CustomerDetail, type System,
  } from "#lib/customers.js";
  import { date } from "#lib/format.js";
  import type { SideGroup } from "#lib/sidelist.js";
  import { toast } from "#lib/toast.svelte.js";

  // The customer's systems, as in the mockup: a side list grouped Servers, Network,
  // Cloud, Printers and Retired, virtual machines under their host, and the chosen
  // system's details, maintenance and what runs on it. Technicians and Managers
  // both keep them up to date.
  const shared = sharedCustomer();
  const customer = $derived(shared.current);
  const systems = $derived(customer?.systems ?? []);
  const base = $derived(resolve("/(app)/customers/[id]/systems", { id: String(customer?.id ?? "") }));
  const wanted = $derived(Number(page.url.searchParams.get("system")) || null);
  const chosen = $derived(systems.find((s) => s.id === wanted) ?? systemGroups(systems)[0]?.systems[0]?.system ?? null);
  const guests = $derived(chosen ? systems.filter((s) => s.parent_id === chosen.id) : []);
  const host = $derived(chosen?.parent_id ? systems.find((s) => s.id === chosen.parent_id) ?? null : null);
  const site = $derived(chosen?.site_id ? customer?.sites?.find((s) => s.id === chosen.site_id) ?? null : null);
  const onSite = $derived(site?.contact_id ? customer?.contacts?.find((c) => c.id === site.contact_id) ?? null : null);

  const groups = $derived(systemGroups(systems).map((group): SideGroup => ({
    label: group.label,
    tone: group.key === "retired" ? "critical" : "neutral",
    items: group.systems.map(({ system, guest }) => ({
      id: system.id,
      label: system.name,
      href: `${base}?system=${system.id}`,
      mono: true,
      indent: guest,
      note: system.role || SYSTEM_TYPES[system.type],
      tags: [
        ...(system.type === "virtual_machine" ? [{ tone: "info" as const, text: "VM" }] : []),
        ...(systems.some((s) => s.parent_id === system.id) ? [{ tone: "neutral" as const, text: "Host" }] : []),
      ],
      keywords: `${system.ip} ${system.serial} ${system.hostname}`,
    })),
  })));

  let draft = $state<(Omit<System, "id"> & { id: number | null }) | null>(null);
  let editOpen = $state(false);
  let removeOpen = $state(false);
  let error = $state<string | null>(null);
  let busy = $state(false);

  // A system may run on any other, but not on itself or on what runs on it.
  const hostChoices = $derived.by(() => {
    if (!draft) return [];
    const below: number[] = [];
    const walk = (id: number) => {
      for (const s of systems) if (s.parent_id === id && !below.includes(s.id)) { below.push(s.id); walk(s.id); }
    };
    if (draft.id !== null) { below.push(draft.id); walk(draft.id); }
    return systems.filter((s) => !below.includes(s.id) && !s.retired_on);
  });

  function edit(found?: System) {
    draft = found ? { ...found } : { id: null, ...emptySystem() };
    error = null;
    editOpen = true;
  }

  async function run(action: () => Promise<CustomerDetail>, done: string): Promise<CustomerDetail | null> {
    busy = true;
    error = null;
    try {
      const detail = await action();
      shared.use(detail);
      toast(done, "ok", { key: "saved" });
      return detail;
    } catch (e) {
      if (!sessionGone(e)) error = e instanceof ApiError ? e.message : "Something went wrong. Try again.";
      return null;
    } finally {
      busy = false;
    }
  }

  async function save(event: SubmitEvent) {
    event.preventDefault();
    if (!draft) return;
    const { id: systemId, ...fields } = draft;
    const body = Object.fromEntries(Object.entries(fields).map(([key, value]) => [key, value === "" && /_on$|_end$|_since$|last_update/.test(key) ? null : value]));
    const url = `/customers/${customer?.id}/systems`;
    const saved = await run(() => systemId === null ? api("POST", url, body) : api("PUT", `${url}/${systemId}`, body),
      "System saved.");
    if (saved) editOpen = false;
  }

  async function remove() {
    if (!chosen) return;
    const gone = chosen;
    removeOpen = false;
    await run(() => api("DELETE", `/customers/${customer?.id}/systems/${gone.id}`), `${gone.name} is removed.`);
  }

  const yesNo = (value: boolean | null) => (value === null ? "Not known" : value ? "Yes" : "No");
</script>

<svelte:head><title>{pageTitle(`Systems · ${customer?.name ?? "Customer"}`)}</title></svelte:head>

{#if customer}
  {#if systems.length}
    <div class="layout">
      <SideList label="{customer.name}'s systems" {groups} selected={chosen?.id ?? null} filterLabel="Name, IP or serial">
        {#snippet footer()}
          {#if customer.may_edit}
            <button class="button button-secondary add" type="button" onclick={() => edit()}>
              <Plus size={16} aria-hidden="true" />Add a system
            </button>
          {/if}
        {/snippet}
      </SideList>

      {#if chosen}
        <div class="detail">
          <section class="section head" aria-labelledby="system-title">
            <div class="title-row">
              <div class="names">
                <h2 class="system-name mono" id="system-title">{chosen.name}</h2>
                <p class="small muted">{[chosen.role, SYSTEM_TYPES[chosen.type]].filter(Boolean).join(" · ")}</p>
                <div class="tags">
                  {#if guests.length}<Pill tone="neutral" text="Host" />{/if}
                  {#if chosen.type === "virtual_machine"}<Pill tone="info" text="VM" />{/if}
                  {#if chosen.retired_on}
                    <Pill tone="critical" text="Retired {date(chosen.retired_on)}" />
                  {:else}
                    <Pill tone="ok" text="Active" />
                  {/if}
                </div>
              </div>
              {#if customer.may_edit}
                <div class="button-row">
                  <button class="button button-accent" type="button" onclick={() => edit(chosen ?? undefined)}>
                    <Pencil size={16} aria-hidden="true" />Change system
                  </button>
                  <RowMenu label="More for {chosen.name}" items={[
                    { label: "Remove system", icon: Trash, danger: true, run: () => (removeOpen = true) },
                  ]} />
                </div>
              {/if}
            </div>

            <div class="tiles">
              <div class="tile">
                <p class="label">Runs on</p>
                {#if host}
                  <!-- eslint-disable-next-line svelte/no-navigation-without-resolve -- base comes from resolve() -->
                  <a class="mono strong" href="{base}?system={host.id}">{host.name}</a>
                  <span class="small muted">{host.role || SYSTEM_TYPES[host.type]}</span>
                {:else}
                  <span class="strong">{guests.length ? `Host for ${guests.length}` : "Its own hardware"}</span>
                  <span class="small muted">{guests.length ? guests.map((g) => g.name).join(", ") : "No host"}</span>
                {/if}
              </div>
              <div class="tile">
                <p class="label">Site</p>
                <span class="strong">{site?.name ?? "No site"}</span>
                {#if site?.address}<span class="small muted address">{site.address}</span>{/if}
              </div>
              {#if onSite}
                <div class="tile contact">
                  <p class="label">On-site contact</p>
                  <ContactCard contact={onSite} inset />
                </div>
              {/if}
            </div>
          </section>

          <div class="columns">
            <section class="section" aria-labelledby="details-title">
              <h3 class="section-title" id="details-title">Details</h3>
              <dl class="facts">
                <dt>Group</dt><dd>{SYSTEM_GROUPS[chosen.group]}</dd>
                <dt>Host name</dt><dd class="mono">{chosen.hostname || "—"}</dd>
                <dt>IP address</dt><dd class="mono">{chosen.ip || "—"}</dd>
                <dt>Hardware</dt><dd>{chosen.hardware || "—"}</dd>
                <dt>Serial number</dt><dd class="mono">{chosen.serial || "—"}</dd>
                <dt>Operating system</dt><dd>{chosen.os || "—"}</dd>
                <dt>In service since</dt><dd>{date(chosen.in_service_since)}</dd>
                <dt>Warranty ends</dt><dd>{date(chosen.warranty_end)}</dd>
                <dt>Notes</dt><dd class="address">{chosen.notes || "—"}</dd>
              </dl>
              <p class="small muted">Passwords stay in the team's password manager, never in Þing.</p>
            </section>

            <section class="section" aria-labelledby="maintenance-title">
              <h3 class="section-title" id="maintenance-title">Maintenance and backup</h3>
              <dl class="facts">
                <dt>Updates itself</dt><dd>{yesNo(chosen.updates_itself)}</dd>
                <dt>May update in working hours</dt><dd>{yesNo(chosen.may_update_in_working_hours)}</dd>
                <dt>Rhythm</dt><dd>{chosen.update_rhythm || "—"}</dd>
                <dt>Last update</dt><dd>{date(chosen.last_update)}</dd>
                <dt>Monitoring</dt><dd>{chosen.monitoring || "—"}</dd>
                <dt>Backup</dt><dd>{chosen.backup || "—"}</dd>
              </dl>
            </section>
          </div>

          {#if guests.length}
            <section class="section" aria-labelledby="guests-title">
              <h3 class="section-title" id="guests-title">Runs on this host</h3>
              <ul class="guests">
                {#each guests as guest (guest.id)}
                  <li>
                    <!-- eslint-disable-next-line svelte/no-navigation-without-resolve -- base comes from resolve() -->
                    <a class="mono strong" href="{base}?system={guest.id}">{guest.name}</a>
                    <span class="small muted">{guest.role || SYSTEM_TYPES[guest.type]}</span>
                  </li>
                {/each}
              </ul>
            </section>
          {/if}
        </div>
      {/if}
    </div>
  {:else}
    <section class="empty">
      <p>No systems yet.</p>
      <p class="small muted">Servers, virtual machines on their host, network gear, cloud tenants and printers.</p>
      {#if customer.may_edit}
        <div><button class="button button-accent" type="button" onclick={() => edit()}>
          <Plus size={16} aria-hidden="true" />Add a system
        </button></div>
      {/if}
    </section>
  {/if}
{/if}

<Dialog bind:open={editOpen} size="wide" title={draft?.id ? `Change ${draft.name}` : "Add a system"}>
  {#if editOpen && draft}
    <form class="stack" onsubmit={save}>
      {#if error}<p class="alert alert-critical" role="alert">{error}</p>{/if}
      <div class="field-grid">
        <div class="field">
          <label for="system-name">Name</label>
          <input id="system-name" class="input mono" required maxlength="100" bind:value={draft.name} />
        </div>
        <div class="field">
          <label for="system-role">Role</label>
          <input id="system-role" class="input" maxlength="150" placeholder="DC and file server" bind:value={draft.role} />
        </div>
        <div class="field">
          <label for="system-group">Group</label>
          <select id="system-group" class="input" bind:value={draft.group}>
            {#each Object.entries(SYSTEM_GROUPS) as [value, name] (value)}<option {value}>{name}</option>{/each}
          </select>
        </div>
        <div class="field">
          <label for="system-type">Type</label>
          <select id="system-type" class="input" bind:value={draft.type}>
            {#each Object.entries(SYSTEM_TYPES) as [value, name] (value)}<option {value}>{name}</option>{/each}
          </select>
        </div>
        <div class="field">
          <label for="system-host">Runs on</label>
          <select id="system-host" class="input" bind:value={draft.parent_id}>
            <option value={null}>Its own hardware</option>
            {#each hostChoices as choice (choice.id)}<option value={choice.id}>{choice.name}</option>{/each}
          </select>
        </div>
        <div class="field">
          <label for="system-site">Site</label>
          <select id="system-site" class="input" bind:value={draft.site_id}>
            <option value={null}>No site</option>
            {#each customer?.sites ?? [] as place (place.id)}<option value={place.id}>{place.name}</option>{/each}
          </select>
        </div>
        <div class="field">
          <label for="system-hostname">Host name</label>
          <input id="system-hostname" class="input mono" maxlength="253" bind:value={draft.hostname} />
        </div>
        <div class="field">
          <label for="system-ip">IP address</label>
          <input id="system-ip" class="input mono" maxlength="100" bind:value={draft.ip} />
        </div>
        <div class="field">
          <label for="system-hardware">Hardware</label>
          <input id="system-hardware" class="input" maxlength="200" bind:value={draft.hardware} />
        </div>
        <div class="field">
          <label for="system-serial">Serial number</label>
          <input id="system-serial" class="input mono" maxlength="100" bind:value={draft.serial} />
        </div>
        <div class="field span-2">
          <label for="system-os">Operating system or firmware</label>
          <input id="system-os" class="input" maxlength="150" bind:value={draft.os} />
        </div>
        <div class="field">
          <label for="system-since">In service since</label>
          <input id="system-since" class="input" type="date" bind:value={draft.in_service_since} />
        </div>
        <div class="field">
          <label for="system-warranty">Warranty ends</label>
          <input id="system-warranty" class="input" type="date" bind:value={draft.warranty_end} />
        </div>
        <div class="field">
          <label for="system-retired">Retired on</label>
          <input id="system-retired" class="input" type="date" aria-describedby="system-retired-hint" bind:value={draft.retired_on} />
        </div>
        <p class="hint beside" id="system-retired-hint">
          Leave empty while it's in use. A retired system stays, under Retired.
        </p>
      </div>
      <fieldset class="checks">
        <legend class="check-title">Maintenance and backup</legend>
        <div class="field-grid">
          <div class="field">
            <label for="system-self">Updates itself</label>
            <select id="system-self" class="input" bind:value={draft.updates_itself}>
              <option value={null}>Not known</option><option value={true}>Yes</option><option value={false}>No</option>
            </select>
          </div>
          <div class="field">
            <label for="system-hours">May update in working hours</label>
            <select id="system-hours" class="input" bind:value={draft.may_update_in_working_hours}>
              <option value={null}>Not known</option><option value={true}>Yes</option><option value={false}>No</option>
            </select>
          </div>
          <div class="field">
            <label for="system-rhythm">Rhythm</label>
            <input id="system-rhythm" class="input" maxlength="100" placeholder="Every 3 months" bind:value={draft.update_rhythm} />
          </div>
          <div class="field">
            <label for="system-last">Last update</label>
            <input id="system-last" class="input" type="date" bind:value={draft.last_update} />
          </div>
          <div class="field span-2">
            <label for="system-monitoring">Monitoring</label>
            <input id="system-monitoring" class="input" maxlength="300" bind:value={draft.monitoring} />
          </div>
          <div class="field span-2">
            <label for="system-backup">Backup</label>
            <input id="system-backup" class="input" maxlength="300" bind:value={draft.backup} />
          </div>
        </div>
      </fieldset>
      <div class="field">
        <label for="system-notes">Notes</label>
        <textarea id="system-notes" class="input" rows="2" maxlength="2000" bind:value={draft.notes}></textarea>
      </div>
      <div class="button-row end">
        <button class="button button-secondary" type="button" onclick={() => (editOpen = false)}>Cancel</button>
        <button class="button button-primary" type="submit" disabled={busy}>Save system</button>
      </div>
    </form>
  {/if}
</Dialog>

<Dialog bind:open={removeOpen} title="Remove {chosen?.name ?? ''}">
  <p>
    The system is removed from this customer, and the change is logged. What runs on it stays,
    without a host. To keep its history, set the day it was retired instead.
  </p>
  {#snippet actions()}
    <button class="button button-secondary" type="button" onclick={() => (removeOpen = false)}>Cancel</button>
    <button class="button button-primary" type="button" disabled={busy} onclick={remove}>Remove system</button>
  {/snippet}
</Dialog>

<style>
  .layout {
    display: grid;
    grid-template-columns: minmax(220px, 260px) minmax(0, 1fr);
    gap: var(--space-4);
    align-items: start;
  }
  .detail {
    display: flex;
    flex-direction: column;
    gap: var(--space-4);
    min-width: 0;
  }
  .title-row {
    display: flex;
    flex-wrap: wrap;
    align-items: flex-start;
    justify-content: space-between;
    gap: var(--space-3);
  }
  .names {
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
  }
  .system-name {
    margin: 0;
    font-size: 28px;
    line-height: 34px;
  }
  .names p {
    margin: 0;
  }
  .tags {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2);
  }
  .tiles {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: var(--space-3);
    margin-top: var(--space-4);
  }
  .tile {
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
    padding: var(--space-3) var(--space-4);
    border-radius: var(--radius-md);
    background: var(--bg);
  }
  .tile.contact {
    grid-column: span 1;
  }
  .label {
    margin: 0;
    color: var(--text-muted);
    font: var(--type-label);
  }
  .strong {
    font-weight: 600;
  }
  .columns {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
    gap: var(--space-4);
  }
  .guests {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    margin: 0;
    padding: 0;
    list-style: none;
  }
  .guests li {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2);
    align-items: baseline;
  }
  .address {
    white-space: pre-line;
  }
  /* A word about the field beside it, level with its box. */
  .beside {
    align-self: end;
    min-height: 44px;
    color: var(--text-muted);
    font: var(--type-body-sm);
  }
  .add {
    width: 100%;
    justify-content: center;
  }
  .empty {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    padding: var(--space-8);
    border: 1px dashed var(--border-strong);
    border-radius: var(--radius-lg);
    text-align: center;
    align-items: center;
  }
  .empty p {
    margin: 0;
  }
  .end {
    justify-content: flex-end;
  }
  @media (max-width: 760px) {
    .layout {
      grid-template-columns: minmax(0, 1fr);
    }
  }
</style>
