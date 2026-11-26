<script lang="ts">
  import { resolve } from "$app/paths";
  import { page } from "$app/state";
  import Check from "@lucide/svelte/icons/check";
  import Gavel from "@lucide/svelte/icons/gavel";
  import LocateFixed from "@lucide/svelte/icons/locate-fixed";
  import Pencil from "@lucide/svelte/icons/pencil";
  import Plus from "@lucide/svelte/icons/plus";
  import RefreshCw from "@lucide/svelte/icons/refresh-cw";
  import Trash from "@lucide/svelte/icons/trash-2";
  import { onMount, tick } from "svelte";
  import { api, ApiError, sessionGone } from "#lib/api.js";
  import { pageTitle } from "#lib/branding.svelte.js";
  import LogWorkDialog from "#lib/components/LogWorkDialog.svelte";
  import Pill from "#lib/components/Pill.svelte";
  import PlanningDialogs from "#lib/components/PlanningDialogs.svelte";
  import RowMenu, { type MenuItem } from "#lib/components/RowMenu.svelte";
  import Switch from "#lib/components/Switch.svelte";
  import { sharedCustomer } from "#lib/context.js";
  import type { CustomerDetail } from "#lib/customers.js";
  import { aheadUntil } from "#lib/general.svelte.js";
  import { REASONS, decisionPill, dueWords, today, warnLine, type Renewal, type Task } from "#lib/planning.js";
  import {
    TIMELINE_TYPES, TYPE_GROUPS, filterTimeline, longDay, shortDay, timelineItems, timelineMonths,
    type TimelineItem, type TypeGroup,
  } from "#lib/timeline.js";
  import type { LogEntry, LogPage } from "#lib/worklog.js";

  // One customer's line, as in the mockup: what's coming up above today (tasks,
  // recurring work, renewals, agreement dates) and what was done below (the work
  // log), by month and week. Only the line scrolls, and it opens on today.
  const shared = sharedCustomer();
  const customer = $derived(shared.current);
  const id = $derived(String(customer?.id ?? ""));

  let entries = $state<LogEntry[]>([]);
  let total = $state(0);
  let loaded = $state(false);
  let error = $state<string | null>(null);
  let period = $state<"90d" | "year" | "all">("year");
  let serviceId = $state<number | null>(null);
  let systemId = $state<number | null>(null);
  let hidden = $state<TypeGroup[]>([]);
  let everyWeek = $state(false);
  const now = today();

  let planning = $state<ReturnType<typeof PlanningDialogs>>();
  let logOpen = $state(false);

  const params = $derived.by(() => {
    const chosen = new URLSearchParams({ period, limit: "500" });
    if (serviceId !== null) chosen.set("service_id", String(serviceId));
    if (systemId !== null) chosen.set("system_id", String(systemId));
    return chosen.toString();
  });
  const items = $derived(customer
    ? filterTimeline(timelineItems(customer, entries, now), { service_id: serviceId, system_id: systemId, hidden })
    : []);
  const months = $derived(timelineMonths(items, now, everyWeek));

  // The work log's part of the line; it loads again when the customer changes (a
  // task ticked off is a new entry) or a filter does.
  $effect(() => {
    const [of, chosen] = [customer?.id, params];
    void customer;
    if (of === undefined) return;
    let stale = false;
    api<LogPage>("GET", `/customers/${of}/log?${chosen}`).then((found) => {
      if (stale) return;
      [entries, total, loaded, error] = [found.entries, found.total, true, null];
    }).catch((e: unknown) => {
      if (!stale && !sessionGone(e)) error = e instanceof ApiError ? e.message : "The timeline could not be loaded.";
    });
    return () => (stale = true);
  });

  // Only the line scrolls: the two columns are as tall as the screen has room for.
  let layout = $state<HTMLElement>();
  let line = $state<HTMLElement>();
  let height = $state<number | null>(null);

  function fit() {
    if (!layout) return;
    const wide = window.matchMedia("(min-width: 861px)").matches;
    const top = layout.getBoundingClientRect().top + window.scrollY;
    height = wide ? Math.max(460, window.innerHeight - top - 32) : null;
  }

  onMount(() => {
    fit();
    window.addEventListener("resize", fit);
    return () => window.removeEventListener("resize", fit);
  });

  // What's above the columns (pinned warnings, the header) can change their room.
  $effect(() => {
    void customer;
    void tick().then(fit);
  });

  /** Scrolls the line, not the page, so today's row sits about halfway down. */
  function jumpToToday() {
    const row = line?.querySelector<HTMLElement>("[data-today]");
    if (!line || !row) return;
    line.scrollTop += row.getBoundingClientRect().top - line.getBoundingClientRect().top
      - (line.clientHeight - row.offsetHeight) / 2;
  }

  // A link from My work or the overview asks for one item ("?show=task-12"): the
  // line opens on it, marked, where it otherwise opens on today.
  const wanted = $derived(page.url.searchParams.get("show"));
  let shown = $state<string | null>(null);

  /** Scrolls the line so the item sits about halfway down. False when it isn't on it. */
  function jumpTo(key: string): boolean {
    const row = [...(line?.querySelectorAll<HTMLElement>("[data-key]") ?? [])].find((r) => r.dataset.key === key);
    if (!line || !row) return false;
    line.scrollTop += row.getBoundingClientRect().top - line.getBoundingClientRect().top
      - (line.clientHeight - row.offsetHeight) / 2;
    return true;
  }

  // It opens on today, or on the item asked for: once per customer and item.
  let placedFor: string | null = null;
  $effect(() => {
    void months;
    const place = `${customer?.id}:${wanted ?? ""}`;
    if (!loaded || !customer || placedFor === place) return;
    placedFor = place;
    void tick().then(() => {
      fit();
      shown = wanted !== null && jumpTo(wanted) ? wanted : null;
      if (shown === null) jumpToToday();
    });
  });

  function toggle(group: TypeGroup, shown: boolean) {
    hidden = shown ? hidden.filter((g) => g !== group) : [...hidden, group];
  }

  function taskMenu(task: Task): MenuItem[] {
    return [
      { label: "Mark done", icon: Check, run: () => planning?.finishTask(task) },
      { label: "Change task", icon: Pencil, run: () => planning?.changeTask(task) },
      ...(task.may_remove ? [{ label: "Remove task", icon: Trash, danger: true, run: () => planning?.removeTask(task) }] : []),
    ];
  }

  function renewalMenu(renewal: Renewal, manages: boolean): MenuItem[] {
    return [
      ...(renewal.decision === "renewed" ? []
        : [{ label: "Mark as renewed", icon: RefreshCw, run: () => planning?.markRenewed(renewal) }]),
      ...(manages ? [{ label: "Record the decision", icon: Gavel, run: () => planning?.decideRenewal(renewal) }] : []),
      { label: "Change renewal", icon: Pencil, run: () => planning?.changeRenewal(renewal) },
      ...(manages ? [{ label: "Remove renewal", icon: Trash, danger: true, run: () => planning?.removeRenewal(renewal) }] : []),
    ];
  }

  const STATES = { coming: "Coming up", overdue: "Overdue", done: "Done" } as const;

  function refresh() {
    void api<CustomerDetail>("GET", `/customers/${id}`).then(shared.use).catch(() => null);
  }
</script>

<svelte:head><title>{pageTitle(`Timeline · ${customer?.name ?? "Customer"}`)}</title></svelte:head>

{#snippet entry(item: TimelineItem, detail: CustomerDetail)}
  <li class="item {item.state}" class:shown={item.key === shown} data-key={item.key}>
    <span class="dot" aria-hidden="true"></span>
    <div class="body">
      <span class="top">
        <span class="visually-hidden">{STATES[item.state]}:</span>
        <time class="small mono when" datetime={item.entry?.happened_at ?? item.day}>{shortDay(item.day)}{item.time ? ` · ${item.time}` : ""}</time>
        <Pill tone="info" text={TIMELINE_TYPES[item.type]} />
        {#if item.renewal}<Pill {...decisionPill(item.renewal, now, aheadUntil(now))} />{/if}
        {#if item.state === "overdue" && (!item.renewal || item.renewal.decision)}
          <Pill tone="critical" text={dueWords(item.day, now)} />
        {/if}
        {#if item.entry?.coverage === "billable"}<Pill tone="warning" text="Billable, no agreement" />{/if}
      </span>
      {#if item.agreement}
        <!-- eslint-disable-next-line svelte/no-navigation-without-resolve -- the path comes from resolve() -->
        <a class="what" href="{resolve("/(app)/customers/[id]/agreements", { id })}?agreement={item.agreement.id}">{item.title}</a>
      {:else}
        <span class="what">{item.title}</span>
      {/if}
      {#if item.detail}<span class="small muted">{item.detail}</span>{/if}
      {#if item.task?.notes}<span class="small notes">{item.task.notes}</span>{/if}
      {#if item.renewal}
        <span class="small muted">
          {warnLine(item.renewal)}{#if item.renewal.decision === "declined" && item.renewal.reason}
            · {REASONS[item.renewal.reason]}{item.renewal.fallback ? ` · Before it runs out: ${item.renewal.fallback}` : ""}{/if}
        </span>
      {/if}
    </div>
    {#if detail.may_edit && (item.task || item.renewal)}
      <div class="acts">
        {#if item.state === "overdue" && item.task}
          {@const task = item.task}
          <button class="button button-secondary" type="button" onclick={() => planning?.finishTask(task)}>Mark done</button>
        {:else if item.state === "overdue" && item.renewal}
          {@const renewal = item.renewal}
          <button class="button button-secondary" type="button" onclick={() => planning?.markRenewed(renewal)}>Mark as renewed</button>
        {/if}
        <RowMenu label="Actions for “{item.title}”"
          items={item.task ? taskMenu(item.task) : renewalMenu(item.renewal!, detail.may_manage)} />
      </div>
    {/if}
  </li>
{/snippet}

{#if customer}
  <div class="heading-row">
    <p class="small muted">What's coming up for {customer.name} above today, what was done below.</p>
    <div class="button-row">
      {#if customer.may_edit}
        <button class="button button-accent" type="button" onclick={() => planning?.newTask()}>
          <Plus size={16} aria-hidden="true" />New task
        </button>
        <button class="button button-secondary" type="button" onclick={() => planning?.newRenewal()}>New renewal</button>
        <button class="button button-secondary" type="button" onclick={() => (logOpen = true)}>Log work</button>
      {/if}
    </div>
  </div>

  {#if error}<p class="alert alert-critical" role="alert">{error}</p>{/if}

  <div class="layout" bind:this={layout} style:height={height ? `${height}px` : undefined}>
    <section class="section line-card" aria-labelledby="line-title">
      <div class="line-head">
        <h2 class="section-title" id="line-title">Timeline</h2>
        <button class="link-button" type="button" onclick={jumpToToday}>
          <LocateFixed size={14} aria-hidden="true" />Jump to today
        </button>
      </div>
      <!-- Focusable, so the keyboard can scroll it. -->
      <!-- svelte-ignore a11y_no_noninteractive_tabindex -->
      <div class="line" bind:this={line} tabindex="0" role="group" aria-label="The line, the latest first">
        <div class="track">
          {#each months as month (month.key)}
            <section class="month" aria-label={month.label}>
              <h3 class="month-head">{month.label}</h3>
              {#each month.rows as row (row.key)}
                {#if row.kind === "gap"}
                  <p class="gap small muted"><span class="mono">{row.weeks}</span> · {row.future ? "Nothing planned" : "Nothing logged"}</p>
                {:else}
                  <div class="week">
                    <div class="week-label small"><span class="mono strong">W {row.week}</span><span class="muted">{row.range}</span></div>
                    <ul class="items">
                      {#each row.items as item (item === "today" ? "today" : item.key)}
                        {#if item === "today"}
                          <li class="item today" data-today>
                            <span class="dot" aria-hidden="true"></span>
                            <span class="today-words"><span class="strong">Today</span><span class="small muted">{longDay(now)}</span></span>
                          </li>
                        {:else}
                          {@render entry(item, customer)}
                        {/if}
                      {:else}
                        <li class="item nothing small muted">{row.future ? "Nothing planned" : "Nothing logged"}</li>
                      {/each}
                    </ul>
                  </div>
                {/if}
              {/each}
            </section>
          {/each}
          {#if loaded && total > entries.length}
            <p class="gap small muted">Showing the newest {entries.length} of {total} work log entries. Narrow it down with the filters.</p>
          {/if}
        </div>
      </div>
    </section>

    <aside class="side" aria-label="Filters and legend">
      <section class="section stack" aria-labelledby="filters-title">
        <h2 class="section-title" id="filters-title">Filters</h2>
        <div class="field">
          <label for="line-service">Service</label>
          <select id="line-service" class="input" bind:value={serviceId}>
            <option value={null}>All services</option>
            {#each customer.services ?? [] as service (service.id)}<option value={service.id}>{service.name}</option>{/each}
          </select>
        </div>
        <div class="field">
          <label for="line-system">System</label>
          <select id="line-system" class="input" bind:value={systemId}>
            <option value={null}>All systems</option>
            {#each customer.systems ?? [] as system (system.id)}<option value={system.id}>{system.name}</option>{/each}
          </select>
        </div>
        <fieldset class="checks">
          <legend class="check-title">Show by type</legend>
          {#each Object.entries(TYPE_GROUPS) as [group, label] (group)}
            <label class="check">
              <input type="checkbox" checked={!hidden.includes(group as TypeGroup)}
                onchange={(event) => toggle(group as TypeGroup, event.currentTarget.checked)} />
              <span>{label}</span>
            </label>
          {/each}
        </fieldset>
        <div class="field">
          <label for="line-period">How far back</label>
          <select id="line-period" class="input" bind:value={period}>
            <option value="90d">Last 90 days</option><option value="year">Last year</option><option value="all">Everything</option>
          </select>
        </div>
        <Switch bind:checked={everyWeek} title="Show empty weeks" />
      </section>
      <section class="section legend" aria-labelledby="legend-title">
        <h2 class="section-title" id="legend-title">Reading the line</h2>
        <ul class="key">
          <li class="item coming"><span class="dot" aria-hidden="true"></span><span>Coming up</span></li>
          <li class="item today"><span class="dot" aria-hidden="true"></span><span>Today</span></li>
          <li class="item overdue"><span class="dot" aria-hidden="true"></span><span>Overdue: mark it done, or move it</span></li>
          <li class="item done"><span class="dot" aria-hidden="true"></span><span>Done, from the work log</span></li>
        </ul>
        <p class="small muted">The future is above today, the past below. A task you tick off moves to the work log, on the day it was done; a recurring one comes back, counted from the newest day it was done.</p>
      </section>
    </aside>
  </div>

  <PlanningDialogs bind:this={planning} {customer} onchanged={shared.use} />
  <LogWorkDialog bind:open={logOpen} {customer} onsaved={refresh} />
{/if}

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
    align-items: stretch;
    min-height: 0;
  }
  .line-card {
    gap: 0;
    min-height: 0;
    padding: 0;
    overflow: hidden;
  }
  .line-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-3);
    padding: var(--space-4) var(--space-6);
    border-bottom: 1px solid var(--border);
  }
  .line {
    flex: 1;
    min-height: 0;
    overflow-y: auto;
  }
  .side {
    display: flex;
    flex-direction: column;
    gap: var(--space-4);
    min-height: 0;
    overflow-y: auto;
  }
  .legend {
    flex: 1;
  }

  /* The line itself: one rule from top to bottom, the dots sitting on it. */
  .track {
    --label: 6.5rem;
    --gutter: var(--space-6);
    position: relative;
    padding-bottom: var(--space-6);
  }
  .track::before {
    position: absolute;
    top: 0;
    bottom: 0;
    left: calc(var(--gutter) + var(--label) + 7px);
    width: 2px;
    background: var(--border);
    content: "";
  }
  .month-head {
    position: sticky;
    top: 0;
    z-index: 1;
    margin: 0;
    padding: var(--space-2) var(--gutter);
    border-bottom: 1px solid var(--border);
    background: var(--bg);
    font: var(--type-label);
  }
  .week {
    display: grid;
    grid-template-columns: var(--label) minmax(0, 1fr);
    padding: var(--space-3) var(--gutter) 0;
  }
  .week-label {
    display: flex;
    flex-direction: column;
    padding-top: var(--space-2);
  }
  .items,
  .key {
    display: flex;
    flex-direction: column;
    margin: 0;
    padding: 0;
    list-style: none;
  }
  .item {
    position: relative;
    display: flex;
    align-items: flex-start;
    gap: var(--space-3);
    padding: var(--space-2) 0 var(--space-2) 30px;
  }
  /* The item a link asked for: marked, so it's found at once. */
  .item.shown .body {
    margin: calc(-1 * var(--space-2)) calc(-1 * var(--space-3));
    padding: var(--space-2) var(--space-3);
    border-radius: var(--radius-md);
    background: color-mix(in srgb, var(--link) 12%, transparent);
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--link) 45%, transparent);
  }
  .dot {
    position: absolute;
    top: 12px;
    left: 1px;
    box-sizing: border-box;
    width: 14px;
    height: 14px;
    border: 2px solid var(--text-muted);
    border-radius: 50%;
    background: var(--surface);
    /* The halo that lifts it off the line. */
    box-shadow: 0 0 0 3px var(--surface);
  }
  .done .dot {
    border-color: var(--border-strong);
    background: var(--border-strong);
  }
  .overdue .dot {
    border-color: var(--critical-text);
    background: var(--critical-text);
  }
  .today .dot {
    border-color: var(--text);
    background: var(--text);
    box-shadow: 0 0 0 3px var(--accent);
  }
  .today {
    align-items: center;
    margin: var(--space-2) 0;
  }
  .today-words {
    display: flex;
    flex-wrap: wrap;
    align-items: baseline;
    gap: var(--space-2);
    padding: var(--space-1) var(--space-3);
    border-radius: var(--radius-pill);
    background: var(--surface-subtle);
  }
  .nothing {
    padding-left: 30px;
  }
  .body {
    display: flex;
    flex: 1;
    flex-direction: column;
    gap: 2px;
    min-width: 0;
  }
  .top {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-2);
  }
  .when {
    color: var(--text-muted);
  }
  .what {
    white-space: pre-line;
    overflow-wrap: anywhere;
  }
  .coming .what,
  .overdue .what {
    font-weight: 600;
  }
  .notes {
    white-space: pre-line;
  }
  .acts {
    display: flex;
    flex-shrink: 0;
    align-items: center;
    gap: var(--space-2);
  }
  .gap {
    margin: var(--space-3) 0 0;
    padding: var(--space-1) var(--gutter) var(--space-1) calc(var(--gutter) + var(--label) + 30px);
  }
  .key .item {
    padding-top: var(--space-1);
    padding-bottom: var(--space-1);
  }
  .key .dot {
    top: 8px;
  }
  @media (max-width: 860px) {
    .layout {
      grid-template-columns: minmax(0, 1fr);
    }
    .line {
      max-height: 70vh;
    }
    .side {
      overflow: visible;
    }
  }
  @media (max-width: 640px) {
    .track {
      --label: 0rem;
      --gutter: var(--space-4);
    }
    .week {
      grid-template-columns: minmax(0, 1fr);
    }
    .week-label {
      flex-direction: row;
      gap: var(--space-2);
      padding: 0 0 var(--space-1) 30px;
    }
    .item {
      flex-wrap: wrap;
    }
  }
</style>
