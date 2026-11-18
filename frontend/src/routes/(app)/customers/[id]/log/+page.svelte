<script lang="ts">
  import Download from "@lucide/svelte/icons/download";
  import Pencil from "@lucide/svelte/icons/pencil";
  import Plus from "@lucide/svelte/icons/plus";
  import Search from "@lucide/svelte/icons/search";
  import Trash from "@lucide/svelte/icons/trash-2";
  import { api, ApiError, sessionGone } from "#lib/api.js";
  import { pageTitle } from "#lib/branding.svelte.js";
  import Dialog from "#lib/components/Dialog.svelte";
  import LogWorkDialog from "#lib/components/LogWorkDialog.svelte";
  import Pill from "#lib/components/Pill.svelte";
  import RowMenu from "#lib/components/RowMenu.svelte";
  import { sharedCustomer } from "#lib/context.js";
  import type { CustomerDetail } from "#lib/customers.js";
  import { toast } from "#lib/toast.svelte.js";
  import { LOG_KINDS, LOGGED_KINDS, byDay, hourMinute, initials, type LogEntry, type LogPage } from "#lib/worklog.js";

  // Everything done for the customer, newest first, as in the mockup: entries grouped
  // by day, each with its time, who, type, what was done, and its service, system,
  // case number and coverage; a summary of the last 90 days; filters; and a CSV export
  // of the entries shown. No durations: Þing does no time registration.
  const shared = sharedCustomer();
  const customer = $derived(shared.current);

  let found = $state<LogPage | null>(null);
  let error = $state<string | null>(null);
  let query = $state("");
  let period = $state<"90d" | "year" | "all">("90d");
  let kind = $state("");
  let serviceId = $state<number | null>(null);
  let systemId = $state<number | null>(null);
  let authorId = $state<number | null>(null);
  let billable = $state(false);
  let searchTimer: ReturnType<typeof setTimeout> | undefined;

  let logOpen = $state(false);
  let editing = $state<LogEntry | null>(null);
  let removing = $state<LogEntry | null>(null);
  let removeOpen = $state(false);

  const params = $derived.by(() => {
    const chosen = new URLSearchParams({ period });
    if (query.trim()) chosen.set("q", query.trim());
    if (kind) chosen.set("kind", kind);
    if (serviceId !== null) chosen.set("service_id", String(serviceId));
    if (systemId !== null) chosen.set("system_id", String(systemId));
    if (authorId !== null) chosen.set("author_id", String(authorId));
    if (billable) chosen.set("billable", "true");
    return chosen.toString();
  });
  const days = $derived(byDay(found?.entries ?? []));
  const people = $derived(customer?.assigned ?? []);

  async function load() {
    if (!customer) return;
    try {
      found = await api<LogPage>("GET", `/customers/${customer.id}/log?${params}`);
      error = null;
    } catch (e) {
      if (!sessionGone(e)) error = e instanceof ApiError ? e.message : "The work log could not be loaded.";
    }
  }

  // Loads when the customer or a filter changes; typing waits for a pause.
  $effect(() => {
    void params;
    void customer?.id;
    clearTimeout(searchTimer);
    searchTimer = setTimeout(load, 200);
    return () => clearTimeout(searchTimer);
  });

  async function refreshOverview() {
    // The overview shows the newest entries: fetch the customer again.
    if (!customer) return;
    const detail = await api<CustomerDetail>("GET", `/customers/${customer.id}`).catch(() => null);
    if (detail) shared.use(detail);
  }

  function saved() {
    void load();
    void refreshOverview();
  }

  function log(entry?: LogEntry) {
    editing = entry ?? null;
    logOpen = true;
  }

  async function remove() {
    const gone = removing;
    removeOpen = false;
    if (!gone || !customer) return;
    try {
      await api("DELETE", `/customers/${customer.id}/log/${gone.id}`);
      toast("Entry removed.", "ok");
      saved();
    } catch (e) {
      if (!sessionGone(e)) toast(e instanceof ApiError ? e.message : "Something went wrong.", "critical");
    }
  }
</script>

<svelte:head><title>{pageTitle(`Work log · ${customer?.name ?? "Customer"}`)}</title></svelte:head>

{#if customer}
  <div class="heading-row">
    <p class="small muted">Everything done for {customer.name}, newest first.</p>
    <div class="button-row">
      {#if customer.may_edit}
        <button class="button button-accent" type="button" onclick={() => log()}>
          <Plus size={16} aria-hidden="true" />Log work
        </button>
      {/if}
      <!-- eslint-disable-next-line svelte/no-navigation-without-resolve -- the API's export, a download -->
      <a class="button button-secondary" href="/api/customers/{customer.id}/log/export?{params}" download>
        <Download size={16} aria-hidden="true" />Export CSV
      </a>
    </div>
  </div>

  {#if error}<p class="alert alert-critical" role="alert">{error}</p>{/if}

  <div class="layout">
    <section class="section log" aria-label="Entries">
      <div class="field search">
        <label for="log-search" class="visually-hidden">Search the work log</label>
        <Search class="search-icon" size={16} aria-hidden="true" />
        <input id="log-search" class="input" type="search" placeholder="Search what was done, a system, a case number"
          bind:value={query} />
      </div>
      {#if found}
        {#if days.length}
          {#each days as day (day.day)}
            <div class="day">
              <h2 class="day-rule"><span>{day.day}</span><span class="small muted">{day.entries.length === 1 ? "1 entry" : `${day.entries.length} entries`}</span></h2>
              <ul class="entries">
                {#each day.entries as entry (entry.id)}
                  <li class="entry">
                    <time class="when mono" datetime={entry.happened_at}>{hourMinute(entry.happened_at)}</time>
                    <div class="body">
                      <span class="who">
                        <span class="initials" title={entry.author ?? "Someone who has left"} aria-hidden="true">{initials(entry.author)}</span>
                        <span class="visually-hidden">{entry.author ?? "Someone who has left"}:</span>
                        <Pill tone="info" text={LOG_KINDS[entry.kind]} />
                      </span>
                      <span class="text">{entry.text}</span>
                      <span class="small muted meta">
                        {[entry.service, entry.systems.join(", ") || null, entry.case_number || null,
                          entry.on_site ? "On site" : null, entry.ticket ? `Ticket ID ${entry.ticket}` : null].filter(Boolean).join(" · ")}
                        {#if entry.coverage === "covered"}<Pill tone="ok" text="Covered" />{/if}
                        {#if entry.coverage === "billable"}<Pill tone="warning" text="Billable, no agreement" />{/if}
                      </span>
                    </div>
                    {#if entry.may_change}
                      <RowMenu label="Actions for the entry at {hourMinute(entry.happened_at)}" items={[
                        { label: "Change entry", icon: Pencil, run: () => log(entry) },
                        { label: "Remove entry", icon: Trash, danger: true, run: () => { removing = entry; removeOpen = true; } },
                      ]} />
                    {/if}
                  </li>
                {/each}
              </ul>
            </div>
          {/each}
          {#if found.total > found.entries.length}
            <p class="small muted">Showing the newest {found.entries.length} of {found.total}. Narrow it down with the filters.</p>
          {/if}
        {:else}
          <p class="muted none">{found.summary.entries || period !== "90d" || query ? "Nothing matches." : "Nothing logged in the last 90 days."}</p>
        {/if}
      {/if}
    </section>

    <aside class="side" aria-label="Summary and filters">
      {#if found}
        <section class="section" aria-labelledby="summary-title">
          <h2 class="section-title" id="summary-title">Last 90 days</h2>
          <dl class="facts">
            <dt>Entries</dt><dd>{found.summary.entries}</dd>
            <dt>On-site visits</dt><dd>{found.summary.on_site}</dd>
            <dt>People</dt><dd>{found.summary.people}</dd>
            <dt>Billable, no agreement</dt><dd>{found.summary.billable}</dd>
          </dl>
          {#if found.summary.by_service.length}
            <ul class="by-service">
              {#each found.summary.by_service as [name, count] (name)}
                <li><span>{name}</span><span class="mono">{count}</span></li>
              {/each}
            </ul>
          {/if}
        </section>
      {/if}
      <section class="section stack" aria-labelledby="filters-title">
        <h2 class="section-title" id="filters-title">Filters</h2>
        <div class="field">
          <label for="filter-period">Period</label>
          <select id="filter-period" class="input" bind:value={period}>
            <option value="90d">Last 90 days</option><option value="year">Last year</option><option value="all">Everything</option>
          </select>
        </div>
        <div class="field">
          <label for="filter-author">Technician</label>
          <select id="filter-author" class="input" bind:value={authorId}>
            <option value={null}>Everyone</option>
            {#each people as person (person.id)}<option value={person.id}>{person.display_name}</option>{/each}
          </select>
        </div>
        <div class="field">
          <label for="filter-service">Service</label>
          <select id="filter-service" class="input" bind:value={serviceId}>
            <option value={null}>All services</option>
            {#each customer.services ?? [] as service (service.id)}<option value={service.id}>{service.name}</option>{/each}
          </select>
        </div>
        <div class="field">
          <label for="filter-system">System</label>
          <select id="filter-system" class="input" bind:value={systemId}>
            <option value={null}>All systems</option>
            {#each customer.systems ?? [] as system (system.id)}<option value={system.id}>{system.name}</option>{/each}
          </select>
        </div>
        <div class="field">
          <label for="filter-kind">Type</label>
          <select id="filter-kind" class="input" bind:value={kind}>
            <option value="">All types</option>
            {#each LOGGED_KINDS as value (value)}<option {value}>{LOG_KINDS[value]}</option>{/each}
          </select>
        </div>
        <label class="check"><input type="checkbox" bind:checked={billable} /><span>Only billable</span></label>
      </section>
    </aside>
  </div>

  <LogWorkDialog bind:open={logOpen} {customer} entry={editing} onsaved={saved} />
{/if}

<Dialog bind:open={removeOpen} title="Remove this entry">
  <p>“{removing?.text ?? ""}” is removed from the work log, and the removal is logged.</p>
  {#snippet actions()}
    <button class="button button-secondary" type="button" onclick={() => (removeOpen = false)}>Cancel</button>
    <button class="button button-primary" type="button" onclick={remove}>Remove entry</button>
  {/snippet}
</Dialog>

<style>
  .heading-row {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-3);
    margin-bottom: var(--space-4);
  }
  .layout {
    display: grid;
    grid-template-columns: minmax(0, 1fr) minmax(240px, 300px);
    gap: var(--space-4);
    align-items: start;
  }
  .side {
    display: flex;
    flex-direction: column;
    gap: var(--space-4);
  }
  .search {
    position: relative;
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
  /* A day: a rule from edge to edge with the date sitting in it. */
  .day-rule {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: var(--space-3);
    margin: var(--space-4) calc(-1 * var(--space-6)) 0;
    padding: var(--space-2) var(--space-6);
    border-top: 1px solid var(--border);
    border-bottom: 1px solid var(--border);
    background: var(--bg);
    font: var(--type-label);
  }
  .entries {
    margin: 0;
    padding: 0;
    list-style: none;
  }
  .entry {
    display: grid;
    grid-template-columns: 3.5rem minmax(0, 1fr) auto;
    gap: var(--space-3);
    align-items: center;
    padding: var(--space-3) 0;
  }
  .entry + .entry {
    border-top: 1px solid var(--border);
  }
  .when {
    font-weight: 600;
  }
  .body {
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
    min-width: 0;
  }
  .who,
  .meta {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-2);
  }
  .initials {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 26px;
    height: 26px;
    border-radius: 50%;
    background: var(--info-bg);
    color: var(--info-text);
    font-size: 11px;
    font-weight: 600;
  }
  .text {
    white-space: pre-line;
  }
  .none {
    margin: var(--space-4) 0 0;
  }
  .by-service {
    display: flex;
    flex-direction: column;
    margin: var(--space-3) 0 0;
    padding: 0;
    list-style: none;
  }
  .by-service li {
    display: flex;
    justify-content: space-between;
    padding: var(--space-1) 0;
    border-top: 1px solid var(--border);
    font: var(--type-body-sm);
  }
  @media (max-width: 860px) {
    .layout {
      grid-template-columns: minmax(0, 1fr);
    }
  }
</style>
