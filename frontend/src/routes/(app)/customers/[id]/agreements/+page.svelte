<script lang="ts">
  import { page } from "$app/state";
  import { resolve } from "$app/paths";
  import Pencil from "@lucide/svelte/icons/pencil";
  import Plus from "@lucide/svelte/icons/plus";
  import Trash from "@lucide/svelte/icons/trash-2";
  import X from "@lucide/svelte/icons/x";
  import { api, ApiError, sessionGone } from "#lib/api.js";
  import { pageTitle } from "#lib/branding.svelte.js";
  import Dialog from "#lib/components/Dialog.svelte";
  import Pill from "#lib/components/Pill.svelte";
  import RowMenu from "#lib/components/RowMenu.svelte";
  import SideList from "#lib/components/SideList.svelte";
  import { sharedCustomer } from "#lib/context.js";
  import {
    AGREEMENT_KINDS, currentVersion, emptyAgreement,
    type Agreement, type CustomerDetail,
  } from "#lib/customers.js";
  import { date } from "#lib/format.js";
  import type { SideGroup } from "#lib/sidelist.js";
  import { toast } from "#lib/toast.svelte.js";

  // The customer's agreements, as in the mockup: a side list of active agreements,
  // offers and ended ones, and the chosen one: the signed document's versions, its
  // term and renewal, and what the document says we provide, section by section,
  // each mapped to a service in Þing. Technicians read; Managers create and change.
  const shared = sharedCustomer();
  const customer = $derived(shared.current);
  const agreements = $derived(customer?.agreements ?? []);
  const services = $derived(customer?.services ?? []);
  const active = $derived(services.filter((s) => s.status === "active"));
  const base = $derived(resolve("/(app)/customers/[id]/agreements", { id: String(customer?.id ?? "") }));
  const wanted = $derived(Number(page.url.searchParams.get("agreement")) || null);
  const chosen = $derived(agreements.find((a) => a.id === wanted) ?? agreements[0] ?? null);
  const version = $derived(chosen ? currentVersion(chosen) : null);
  const serviceName = (id: number | null) => services.find((s) => s.id === id)?.name ?? null;
  const covers = $derived(new Set(chosen?.sections.map((s) => s.service_id).filter((id) => id !== null)).size);
  const uncovered = $derived(active.filter((s) => !s.agreement));
  const withWhom = $derived(chosen?.company_id
    ? customer?.companies?.find((c) => c.id === chosen.company_id)?.name ?? null : null);

  const groups = $derived(([["active", "Active", "ok"], ["offer", "Offers", "neutral"], ["ended", "Ended", "critical"]] as const).map(
    ([status, label, tone]): SideGroup => ({
      label, tone,
      items: agreements.filter((a) => a.status === status).map((a) => ({
        id: a.id, label: a.name, href: `${base}?agreement=${a.id}`,
        note: status === "offer" ? "Waiting for the customer" : status === "ended" ? `Ended ${date(a.ends_on)}` : AGREEMENT_KINDS[a.kind],
        noteTone: status === "offer" ? "warning" as const : "muted" as const,
      })),
    })));

  // The Managers' form.
  let draft = $state<(Omit<Agreement, "id"> & { id: number | null }) | null>(null);
  let open = $state(false);
  let removeOpen = $state(false);
  let error = $state<string | null>(null);
  let busy = $state(false);

  function edit(found?: Agreement) {
    draft = found
      ? { ...found, versions: found.versions.map((v) => ({ ...v })), sections: found.sections.map((s) => ({ ...s })) }
      : { id: null, ...emptyAgreement() };
    error = null;
    open = true;
  }

  function addVersion() {
    if (!draft) return;
    const next = Math.max(0, ...draft.versions.map((v) => v.number)) + 1;
    draft.versions.push({ number: next, sent_on: null, signed_on: null, signed_for_customer: "", signed_for_us: "", note: "" });
  }

  async function save(event: SubmitEvent) {
    event.preventDefault();
    if (!draft) return;
    const { id: agreementId, ...fields } = draft;
    const blank = (value: string | null) => value || null;
    const body = {
      ...fields,
      starts_on: blank(fields.starts_on), ends_on: blank(fields.ends_on), notice_by: blank(fields.notice_by),
      versions: fields.versions.map((v) => ({ ...v, sent_on: blank(v.sent_on), signed_on: blank(v.signed_on) })),
      sections: fields.sections.map((s) => ({ ...s, service_id: s.terms ? null : s.service_id })),
    };
    busy = true;
    error = null;
    try {
      const url = `/customers/${customer?.id}/agreements`;
      shared.use(await api<CustomerDetail>(agreementId === null ? "POST" : "PUT",
        agreementId === null ? url : `${url}/${agreementId}`, body));
      open = false;
      toast("Agreement saved.", "ok", { key: "saved" });
    } catch (e) {
      if (!sessionGone(e)) error = e instanceof ApiError ? e.message : "Something went wrong. Try again.";
    } finally {
      busy = false;
    }
  }

  async function remove() {
    if (!chosen) return;
    const gone = chosen;
    removeOpen = false;
    try {
      shared.use(await api<CustomerDetail>("DELETE", `/customers/${customer?.id}/agreements/${gone.id}`));
      toast(`${gone.name} is removed.`, "ok");
    } catch (e) {
      if (!sessionGone(e)) toast(e instanceof ApiError ? e.message : "Something went wrong.", "critical");
    }
  }
</script>

<svelte:head><title>{pageTitle(`Agreements · ${customer?.name ?? "Customer"}`)}</title></svelte:head>

{#if customer}
  {#if agreements.length}
    <div class="layout">
      <SideList label="{customer.name}'s agreements" {groups} selected={chosen?.id ?? null} filterLabel="Filter agreements">
        {#snippet footer()}
          {#if customer.may_manage_agreements}
            <button class="button button-secondary add" type="button" onclick={() => edit()}>
              <Plus size={16} aria-hidden="true" />New agreement
            </button>
          {/if}
        {/snippet}
      </SideList>

      {#if chosen}
        <div class="detail">
          <section class="section" aria-labelledby="agreement-title">
            <div class="title-row">
              <div class="names">
                <h2 class="agreement-name" id="agreement-title">{chosen.name}</h2>
                <p class="small muted">
                  {AGREEMENT_KINDS[chosen.kind]}{withWhom ? ` with ${withWhom}` : ""} ·
                  {version?.signed_on ? `based on the signed document, version ${version.number}` : "no signed version yet"}
                </p>
                <div class="tags">
                  {#if chosen.status === "active"}
                    <Pill tone="ok" text={chosen.starts_on ? `Active since ${date(chosen.starts_on)}` : "Active"} />
                  {:else if chosen.status === "offer"}
                    <Pill tone="warning" text="Offer: waiting for the customer" />
                  {:else}
                    <Pill tone="critical" text="Ended {date(chosen.ends_on)}" />
                  {/if}
                  <Pill tone="neutral" text="Covers {covers} of {active.length} services" />
                  {#if chosen.notice_period}<Pill tone="neutral" text="Notice: {chosen.notice_period}" />{/if}
                </div>
                {#if !customer.may_manage_agreements}
                  <p class="small muted">Read-only: agreements are changed by a Manager.</p>
                {/if}
              </div>
              {#if customer.may_manage_agreements}
                <div class="button-row">
                  <button class="button button-accent" type="button" onclick={() => edit(chosen ?? undefined)}>
                    <Pencil size={16} aria-hidden="true" />Change agreement
                  </button>
                  <RowMenu label="More for {chosen.name}" items={[
                    { label: "Remove agreement", icon: Trash, danger: true, run: () => (removeOpen = true) },
                  ]} />
                </div>
              {/if}
            </div>

            <div class="tiles">
              <div class="tile">
                <p class="label">The signed document</p>
                {#if version}
                  <span class="strong">Version {version.number}{version.signed_on ? `, signed ${date(version.signed_on)}` : ", not signed yet"}</span>
                  {#if version.signed_for_customer}<span class="small">For {customer.name}: {version.signed_for_customer}</span>{/if}
                  {#if version.signed_for_us}<span class="small">For us: {version.signed_for_us}</span>{/if}
                  {#if version.note}<span class="small muted">{version.note}</span>{/if}
                {:else}
                  <span class="strong">No version recorded</span>
                {/if}
              </div>
              <div class="tile">
                <p class="label">Term and renewal</p>
                <span class="strong">{date(chosen.starts_on, "No start")} to {date(chosen.ends_on, "no end")}</span>
                <span class="small">{chosen.auto_renews ? "Renews by itself" : "Doesn't renew by itself"}{chosen.notice_by ? ` · last day to give notice ${date(chosen.notice_by)}` : ""}</span>
                <span class="small muted">
                  {chosen.price_section ? `Price and invoicing: ${chosen.price_section} of the document` : "Þing keeps no prices: see the document"}
                </span>
              </div>
              <div class="tile">
                <p class="label">Response times</p>
                <span class="strong">{chosen.sla ? "Its own" : "The standard SLA"}</span>
                {#if chosen.sla}<span class="small notes">{chosen.sla}</span>{/if}
              </div>
            </div>
          </section>

          <section class="section" aria-labelledby="sections-title">
            <h3 class="section-title" id="sections-title">What the document says we provide</h3>
            {#if chosen.sections.length}
              <div class="table-wrap">
                <table class="table">
                  <thead><tr><th>Section</th><th>Service in Þing</th><th>Agreed</th><th></th></tr></thead>
                  <tbody>
                    {#each chosen.sections as section (section.ref)}
                      <tr>
                        <td class="mono strong">{section.ref}</td>
                        <td>{section.terms ? "—" : serviceName(section.service_id) ?? "—"}</td>
                        <td>{section.text || "—"}</td>
                        <td>
                          {#if section.terms}
                            <Pill tone="neutral" text="Terms" />
                          {:else if section.service_id !== null}
                            <Pill tone="ok" text="Linked" />
                          {:else}
                            <Pill tone="warning" text="Not linked" />
                          {/if}
                        </td>
                      </tr>
                    {/each}
                  </tbody>
                </table>
              </div>
            {:else}
              <p class="muted">No sections recorded yet.</p>
            {/if}
            {#if uncovered.length}
              <p class="alert alert-warning">
                In no agreement: {uncovered.map((s) => s.name).join(", ")}. Work on {uncovered.length === 1 ? "it" : "them"}
                is billable; ask a Manager before promising it's covered.
              </p>
            {/if}
          </section>

          <section class="section" aria-labelledby="versions-title">
            <h3 class="section-title" id="versions-title">Versions</h3>
            {#if chosen.versions.length}
              <ul class="versions">
                {#each chosen.versions.toReversed() as item (item.number)}
                  <li>
                    <span class="strong">Version {item.number}</span>
                    <span class="small muted">
                      {[item.sent_on ? `sent ${date(item.sent_on)}` : null, item.signed_on ? `signed ${date(item.signed_on)}` : "not signed",
                        item.note || null].filter(Boolean).join(" · ")}
                    </span>
                  </li>
                {/each}
              </ul>
            {:else}
              <p class="muted">No versions recorded yet.</p>
            {/if}
            {#if chosen.notes}<p class="notes">{chosen.notes}</p>{/if}
          </section>
        </div>
      {/if}
    </div>
  {:else}
    <section class="empty">
      <p>No agreements yet.</p>
      <p class="small muted">
        What was signed, and which services it covers. Until then, work on every service is billable.
      </p>
      {#if customer.may_manage_agreements}
        <div><button class="button button-accent" type="button" onclick={() => edit()}>
          <Plus size={16} aria-hidden="true" />New agreement
        </button></div>
      {:else}
        <p class="small muted">Agreements are added by a Manager.</p>
      {/if}
    </section>
  {/if}
{/if}

<Dialog bind:open title={draft?.id ? "Change agreement" : "New agreement"}>
  {#if open && draft}
    <form class="stack" onsubmit={save}>
      {#if error}<p class="alert alert-critical" role="alert">{error}</p>{/if}
      <div class="field">
        <label for="agreement-name">Name</label>
        <input id="agreement-name" class="input" required maxlength="150" bind:value={draft.name} />
        <span class="hint">Such as “Service agreement 2024”.</span>
      </div>
      <div class="pair">
        <div class="field">
          <label for="agreement-kind">Kind</label>
          <select id="agreement-kind" class="input" bind:value={draft.kind}>
            {#each Object.entries(AGREEMENT_KINDS) as [value, name] (value)}<option {value}>{name}</option>{/each}
          </select>
        </div>
        <div class="field">
          <label for="agreement-status">Status</label>
          <select id="agreement-status" class="input" bind:value={draft.status}>
            <option value="offer">Offer, waiting for the customer</option>
            <option value="active">Active</option>
            <option value="ended">Ended</option>
          </select>
        </div>
      </div>
      {#if customer?.companies?.length}
        <div class="field">
          <label for="agreement-company">With</label>
          <select id="agreement-company" class="input" bind:value={draft.company_id}>
            <option value={null}>The whole group</option>
            {#each customer.companies as company (company.id)}<option value={company.id}>{company.name}</option>{/each}
          </select>
        </div>
      {/if}
      <div class="pair">
        <div class="field">
          <label for="agreement-start">Starts on</label>
          <input id="agreement-start" class="input" type="date" bind:value={draft.starts_on} />
        </div>
        <div class="field">
          <label for="agreement-end">{draft.status === "ended" ? "Ended on" : "Term ends on"}</label>
          <input id="agreement-end" class="input" type="date" required={draft.status === "ended"} bind:value={draft.ends_on} />
        </div>
      </div>
      <div class="pair">
        <div class="field">
          <label for="agreement-notice">Notice period</label>
          <input id="agreement-notice" class="input" maxlength="100" placeholder="3 months" bind:value={draft.notice_period} />
        </div>
        <div class="field">
          <label for="agreement-notice-by">Last day to give notice</label>
          <input id="agreement-notice-by" class="input" type="date" bind:value={draft.notice_by} />
        </div>
      </div>
      <label class="check"><input type="checkbox" bind:checked={draft.auto_renews} /><span>Renews by itself</span></label>
      <div class="pair">
        <div class="field">
          <label for="agreement-price">Price and invoicing section</label>
          <input id="agreement-price" class="input" maxlength="100" placeholder="§ 5" bind:value={draft.price_section} />
          <span class="hint">Where the document deals with it. Þing keeps no prices.</span>
        </div>
        <div class="field">
          <label for="agreement-sla">Response times</label>
          <input id="agreement-sla" class="input" maxlength="500" bind:value={draft.sla} />
          <span class="hint">Leave empty for the standard SLA.</span>
        </div>
      </div>

      <fieldset class="checks">
        <legend class="check-title">Versions</legend>
        {#each draft.versions as item, n (n)}
          <div class="version-row">
            <div class="field narrow">
              <label for="version-number-{n}">Version</label>
              <input id="version-number-{n}" class="input" type="number" min="1" max="999" required bind:value={item.number} />
            </div>
            <div class="field">
              <label for="version-sent-{n}">Sent</label>
              <input id="version-sent-{n}" class="input" type="date" bind:value={item.sent_on} />
            </div>
            <div class="field">
              <label for="version-signed-{n}">Signed</label>
              <input id="version-signed-{n}" class="input" type="date" bind:value={item.signed_on} />
            </div>
            <button class="icon-button" type="button" aria-label="Remove version {item.number}"
              onclick={() => draft?.versions.splice(n, 1)}><X size={16} aria-hidden="true" /></button>
            <div class="field">
              <label for="version-them-{n}">Signed for the customer</label>
              <input id="version-them-{n}" class="input" maxlength="200" bind:value={item.signed_for_customer} />
            </div>
            <div class="field">
              <label for="version-us-{n}">Signed for us</label>
              <input id="version-us-{n}" class="input" maxlength="200" bind:value={item.signed_for_us} />
            </div>
            <div class="field wide">
              <label for="version-note-{n}">Note</label>
              <input id="version-note-{n}" class="input" maxlength="300" placeholder="Where the signed copy is kept" bind:value={item.note} />
            </div>
          </div>
        {/each}
        <div><button class="button button-secondary" type="button" onclick={addVersion}>
          <Plus size={16} aria-hidden="true" />Add a version
        </button></div>
      </fieldset>

      <fieldset class="checks">
        <legend class="check-title">What the document says we provide</legend>
        {#each draft.sections as section, n (n)}
          <div class="section-row">
            <div class="field narrow">
              <label for="section-ref-{n}">Section</label>
              <input id="section-ref-{n}" class="input mono" required maxlength="20" placeholder="§ 3.1" bind:value={section.ref} />
            </div>
            <div class="field">
              <label for="section-service-{n}">Covers</label>
              <select id="section-service-{n}" class="input" disabled={section.terms} bind:value={section.service_id}>
                <option value={null}>Not linked</option>
                {#each services as service (service.id)}<option value={service.id}>{service.name}</option>{/each}
              </select>
            </div>
            <label class="check small"><input type="checkbox" bind:checked={section.terms} /><span>Terms</span></label>
            <button class="icon-button" type="button" aria-label="Remove {section.ref || 'this section'}"
              onclick={() => draft?.sections.splice(n, 1)}><X size={16} aria-hidden="true" /></button>
            <div class="field wide">
              <label for="section-text-{n}">Agreed</label>
              <input id="section-text-{n}" class="input" maxlength="1000" bind:value={section.text} />
            </div>
          </div>
        {/each}
        <div><button class="button button-secondary" type="button"
          onclick={() => draft?.sections.push({ ref: "", text: "", service_id: null, terms: false })}>
          <Plus size={16} aria-hidden="true" />Add a section
        </button></div>
      </fieldset>

      <div class="field">
        <label for="agreement-notes">Notes</label>
        <textarea id="agreement-notes" class="input" rows="2" maxlength="2000" bind:value={draft.notes}></textarea>
      </div>
      <div class="button-row end">
        <button class="button button-secondary" type="button" onclick={() => (open = false)}>Cancel</button>
        <button class="button button-primary" type="submit" disabled={busy}>Save agreement</button>
      </div>
    </form>
  {/if}
</Dialog>

<Dialog bind:open={removeOpen} title="Remove {chosen?.name ?? ''}">
  <p>For an agreement entered by mistake. One that ran keeps its history: set it to Ended instead.</p>
  {#snippet actions()}
    <button class="button button-secondary" type="button" onclick={() => (removeOpen = false)}>Cancel</button>
    <button class="button button-primary" type="button" onclick={remove}>Remove agreement</button>
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
  .names p {
    margin: 0;
  }
  .agreement-name {
    margin: 0;
    font-family: var(--font-display, Marcellus, Georgia, serif);
    font-size: 32px;
    font-weight: 400;
    line-height: 38px;
  }
  .tags {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2);
  }
  .tiles {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
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
  .label {
    margin: 0;
    color: var(--text-muted);
    font: var(--type-label);
  }
  .strong {
    font-weight: 600;
  }
  .notes {
    white-space: pre-line;
  }
  .versions {
    display: flex;
    flex-direction: column;
    margin: 0;
    padding: 0;
    list-style: none;
  }
  .versions li {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2);
    align-items: baseline;
    padding: var(--space-2) 0;
    border-top: 1px solid var(--border);
  }
  .pair {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
    gap: var(--space-3);
  }
  .version-row,
  .section-row {
    display: grid;
    grid-template-columns: 5.5rem minmax(0, 1fr) minmax(0, 1fr) auto;
    gap: var(--space-2);
    align-items: end;
    padding: var(--space-2) 0;
    border-top: 1px solid var(--border);
  }
  .section-row {
    grid-template-columns: 5.5rem minmax(0, 1fr) auto auto;
  }
  .version-row .wide,
  .section-row .wide {
    grid-column: 1 / -1;
  }
  .version-row .field:nth-of-type(4) {
    grid-column: 1 / 3;
  }
  .add {
    width: 100%;
    justify-content: center;
  }
  .empty {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: var(--space-2);
    padding: var(--space-8);
    border: 1px dashed var(--border-strong);
    border-radius: var(--radius-lg);
    text-align: center;
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
