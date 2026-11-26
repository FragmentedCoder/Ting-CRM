<script lang="ts">
  import { resolve } from "$app/paths";
  import Check from "@lucide/svelte/icons/check";
  import Plus from "@lucide/svelte/icons/plus";
  import { tick } from "svelte";
  import { api, ApiError, sessionGone } from "#lib/api.js";
  import { branding, pageTitle } from "#lib/branding.svelte.js";
  import Dialog from "#lib/components/Dialog.svelte";
  import LogWorkDialog from "#lib/components/LogWorkDialog.svelte";
  import Pill from "#lib/components/Pill.svelte";
  import PlanningDialogs from "#lib/components/PlanningDialogs.svelte";
  import { formatCvr, type CustomerDetail } from "#lib/customers.js";
  import { date } from "#lib/format.js";
  import { aheadWords } from "#lib/general.svelte.js";
  import { DATED_KINDS, firstName, greeting, reasonWords, type MyTask, type MyWork } from "#lib/mywork.js";
  import { decisionPill, dueTone, dueWords, today } from "#lib/planning.js";
  import { roleName } from "#lib/roles.js";
  import { can, session } from "#lib/session.svelte.js";
  import { longDay, shortDay } from "#lib/timeline.js";
  import { toast } from "#lib/toast.svelte.js";
  import { recentCustomers, workspace } from "#lib/workspace.svelte.js";

  // Where the day starts, as in the mockup: the tasks that are yours across
  // customers, the customers that need attention, the renewals and notice days coming
  // up, and the customers you looked at last. Managers also get what's theirs to deal
  // with. Someone who doesn't work with customers (an Auditor) gets a plain welcome.
  const info = $derived(session.current);
  const works = $derived(can(info, "edit_customers"));
  const now = today();

  let work = $state<MyWork | null>(null);
  let error = $state<string | null>(null);

  async function load() {
    try {
      work = await api<MyWork>("GET", "/my-work");
      error = null;
    } catch (e) {
      if (!sessionGone(e)) error = e instanceof ApiError ? e.message : "My work could not be loaded.";
    }
  }

  $effect(() => {
    if (works) void load();
  });

  const customers = $derived(workspace.customers?.filter((c) => c.visibility === "full" && c.status !== "former") ?? []);
  const recent = $derived(recentCustomers());
  const href = (id: number) => resolve("/(app)/customers/[id]", { id: String(id) });
  // Straight to the thing itself: a task or a renewal at its place on the customer's
  // timeline, an agreement's date at the agreement, a case number at its service.
  const onTimeline = (id: number, key: string) =>
    `${resolve("/(app)/customers/[id]/timeline", { id: String(id) })}?show=${key}`;
  const agreementHref = (id: number, agreement: number) =>
    `${resolve("/(app)/customers/[id]/agreements", { id: String(id) })}?agreement=${agreement}`;
  const serviceHref = (id: number, service: number) =>
    `${resolve("/(app)/customers/[id]/services", { id: String(id) })}?service=${service}`;
  const datedHref = (dated: { kind: string; customer_id: number; id: number }) =>
    dated.kind === "renewal" ? onTimeline(dated.customer_id, `renewal-${dated.id}`)
      : agreementHref(dated.customer_id, dated.id);

  // A new task and logging work are a customer's: choose it first (the one open in
  // the menu is offered), then the same forms as on the customer's pages.
  let chosen = $state<CustomerDetail | null>(null);
  let planning = $state<ReturnType<typeof PlanningDialogs>>();
  let logOpen = $state(false);
  let pickOpen = $state(false);
  let pickFor = $state<"task" | "log">("task");
  let pickId = $state<number | null>(null);
  let busy = $state(false);

  async function withCustomer(id: number, then: () => void) {
    busy = true;
    try {
      chosen = await api<CustomerDetail>("GET", `/customers/${id}`);
      await tick();
      then();
    } catch (e) {
      if (!sessionGone(e)) toast(e instanceof ApiError ? e.message : "Something went wrong.", "critical");
    } finally {
      busy = false;
    }
  }

  function pick(what: "task" | "log") {
    pickFor = what;
    pickId = customers.some((c) => c.id === workspace.customerId) ? workspace.customerId : (customers[0]?.id ?? null);
    pickOpen = true;
  }

  function picked(event: SubmitEvent) {
    event.preventDefault();
    if (pickId === null) return;
    pickOpen = false;
    void withCustomer(pickId, () => (pickFor === "task" ? planning?.newTask() : (logOpen = true)));
  }

  function finish(mine: MyTask) {
    void withCustomer(mine.customer_id, () => planning?.finishTask(mine.task));
  }
</script>

<svelte:head><title>{works ? pageTitle("My work") : branding.current.site_name}</title></svelte:head>

{#if info && works}
  <main class="page-content">
    <div class="heading-row">
      <div class="heading">
        <p class="small muted">{longDay(now)}</p>
        <h1 class="title">{greeting()}, {firstName(info.user.display_name)}</h1>
      </div>
      {#if customers.length}
        <div class="button-row">
          <button class="button button-accent" type="button" onclick={() => pick("task")}>
            <Plus size={16} aria-hidden="true" />New task
          </button>
          <button class="button button-secondary" type="button" onclick={() => pick("log")}>Log work</button>
        </div>
      {/if}
    </div>

    {#if error}<p class="alert alert-critical" role="alert">{error}</p>{/if}

    {#if work}
      <dl class="counts" aria-label="At a glance">
        <div class="count" class:critical={work.counts.overdue > 0}>
          <dt>Overdue</dt><dd>{work.counts.overdue}</dd>
        </div>
        <div class="count"><dt>Due this week</dt><dd>{work.counts.this_week}</dd></div>
        <div class="count"><dt>Renewals and notice days, next {aheadWords(work.ahead_months)}</dt><dd>{work.counts.dates}</dd></div>
        <div class="count" class:warning={work.counts.attention > 0}>
          <dt>Customers needing attention</dt><dd>{work.counts.attention}</dd>
        </div>
      </dl>

      <div class="panels">
        <section class="section" aria-labelledby="tasks-title">
          <h2 class="section-title" id="tasks-title">My tasks</h2>
          {#if work.tasks.length}
            <ul class="rows">
              {#each work.tasks as mine (mine.task.id)}
                <li class="task">
                  <button class="tick" type="button" disabled={busy} aria-label="Mark “{mine.task.title}” as done"
                    title="Mark done" onclick={() => finish(mine)}><Check size={14} aria-hidden="true" /></button>
                  <span class="body">
                    <!-- eslint-disable-next-line svelte/no-navigation-without-resolve -- onTimeline() uses resolve() -->
                    <a class="strong what" href={onTimeline(mine.customer_id, `task-${mine.task.id}`)}>{mine.task.title}</a>
                    <span class="small muted">
                      <!-- eslint-disable-next-line svelte/no-navigation-without-resolve -- href() uses resolve() -->
                      <a href={href(mine.customer_id)}>{mine.customer}</a>{mine.task.service ? ` · ${mine.task.service}` : ""}{mine.task.system ? ` · ${mine.task.system}` : ""}
                    </span>
                  </span>
                  <span class="when">
                    <span class="small mono">{shortDay(mine.task.due_on)}</span>
                    <Pill tone={dueTone(mine.task.due_on, now)} text={dueWords(mine.task.due_on, now)} />
                  </span>
                </li>
              {/each}
            </ul>
          {:else}
            <p class="muted">Nothing is waiting for you.</p>
          {/if}
          {#if work.later}
            <p class="small muted">
              {work.later === 1 ? "One more is" : `${work.later} more are`} due after {date(work.ahead_until)},
              further off than the team looks ahead: on its customer's timeline until then.
            </p>
          {/if}
        </section>

        <section class="section" aria-labelledby="attention-title">
          <h2 class="section-title" id="attention-title">Customers needing attention</h2>
          {#if work.attention.length}
            <ul class="rows">
              {#each work.attention as needs (needs.customer_id)}
                <li class="needs">
                  <!-- eslint-disable-next-line svelte/no-navigation-without-resolve -- href() uses resolve() -->
                  <a class="strong" href={href(needs.customer_id)}>{needs.customer}</a>
                  <span class="badges">
                    {#each needs.reasons as reason (reason.kind)}<Pill tone={reason.tone} text={reasonWords(reason, now)} />{/each}
                    {#if needs.more}<span class="small muted">and {needs.more} more</span>{/if}
                  </span>
                </li>
              {/each}
            </ul>
          {:else}
            <p class="muted">Nothing: no overdue tasks, open renewals, notice days or services without agreement.</p>
          {/if}
        </section>

        <section class="section" aria-labelledby="dates-title">
          <h2 class="section-title" id="dates-title">Renewals and notice days</h2>
          {#if work.dates.length}
            <ul class="rows">
              {#each work.dates as dated (`${dated.kind}-${dated.customer_id}-${dated.what}-${dated.day}`)}
                <li class="task">
                  <span class="body">
                    <span class="line">
                      <Pill tone="info" text={DATED_KINDS[dated.kind]} />
                      {#if dated.kind === "renewal"}<Pill {...decisionPill({ decision: dated.decision ?? "", renews_on: dated.day }, now, work.ahead_until)} />{/if}
                      <!-- eslint-disable-next-line svelte/no-navigation-without-resolve -- datedHref() uses resolve() -->
                      <a class="strong what" href={datedHref(dated)}>{dated.what}</a>
                    </span>
                    <!-- eslint-disable-next-line svelte/no-navigation-without-resolve -- href() uses resolve() -->
                    <a class="small" href={href(dated.customer_id)}>{dated.customer}</a>
                  </span>
                  <span class="when">
                    <span class="small mono">{shortDay(dated.day)}</span>
                    <Pill tone={dueTone(dated.day, now)} text={dueWords(dated.day, now)} />
                  </span>
                </li>
              {/each}
            </ul>
          {:else}
            <p class="muted">Nothing in the next {aheadWords(work.ahead_months)}.</p>
          {/if}
        </section>

        <section class="section" aria-labelledby="recent-title">
          <h2 class="section-title" id="recent-title">Recently viewed</h2>
          {#if recent.length}
            <ul class="rows">
              {#each recent as customer (customer.id)}
                <li class="recent">
                  <!-- eslint-disable-next-line svelte/no-navigation-without-resolve -- href() uses resolve() -->
                  <a class="strong" href={href(customer.id)}>{customer.name}</a>
                  <span class="small muted mono">{[customer.cvr ? formatCvr(customer.cvr) : null, customer.town].filter(Boolean).join(" · ")}</span>
                </li>
              {/each}
            </ul>
          {:else}
            <p class="muted">The customers you open show up here.</p>
          {/if}
          <a class="small" href={resolve("/(app)/customers")}>All customers</a>
        </section>
      </div>

      {#if work.managers}
        {@const managers = work.managers}
        <h2 class="group-title">For Managers</h2>
        <div class="panels three">
          <section class="section" aria-labelledby="waiting-title">
            <h3 class="section-title" id="waiting-title">Waiting for the customer</h3>
            {#if managers.waiting.length}
              <ul class="rows">
                {#each managers.waiting as dated (`${dated.customer_id}-${dated.what}-${dated.day}`)}
                  <li class="recent">
                    <!-- eslint-disable-next-line svelte/no-navigation-without-resolve -- datedHref() uses resolve() -->
                    <a class="strong what" href={datedHref(dated)}>{dated.what}</a>
                    <!-- eslint-disable-next-line svelte/no-navigation-without-resolve -- href() uses resolve() -->
                    <span class="small muted"><a href={href(dated.customer_id)}>{dated.customer}</a> · renews {date(dated.day)}</span>
                  </li>
                {/each}
              </ul>
            {:else}
              <p class="muted">No renewal is waiting for a customer's answer.</p>
            {/if}
          </section>
          <section class="section" aria-labelledby="monthly-title">
            <h3 class="section-title" id="monthly-title">Monthly case numbers to replace</h3>
            {#if managers.monthly_cases.length}
              <ul class="rows">
                {#each managers.monthly_cases as found (`${found.customer_id}-${found.service}`)}
                  <li class="recent">
                    <!-- eslint-disable-next-line svelte/no-navigation-without-resolve -- serviceHref() uses resolve() -->
                    <span><span class="mono strong">{found.case_number}</span> <a class="small what" href={serviceHref(found.customer_id, found.service_id)}>{found.service}</a></span>
                    <!-- eslint-disable-next-line svelte/no-navigation-without-resolve -- href() uses resolve() -->
                    <span class="small muted"><a href={href(found.customer_id)}>{found.customer}</a>{found.since ? ` · since ${date(found.since)}` : ""}</span>
                  </li>
                {/each}
              </ul>
            {:else}
              <p class="muted">Every monthly case number is this month's.</p>
            {/if}
          </section>
          <section class="section" aria-labelledby="uncovered-title">
            <h3 class="section-title" id="uncovered-title">Services without agreement</h3>
            {#if managers.uncovered.length}
              <ul class="rows">
                {#each managers.uncovered as found (found.customer_id)}
                  <li class="recent">
                    <!-- eslint-disable-next-line svelte/no-navigation-without-resolve -- href() uses resolve() -->
                    <a class="strong" href={href(found.customer_id)}>{found.customer}</a>
                    <span class="small muted">{found.services.join(", ")}</span>
                  </li>
                {/each}
              </ul>
            {:else}
              <p class="muted">An agreement covers every active service.</p>
            {/if}
          </section>
        </div>
      {/if}
    {/if}
  </main>

  {#if chosen}
    <PlanningDialogs bind:this={planning} customer={chosen} onchanged={load} />
    <LogWorkDialog bind:open={logOpen} customer={chosen} onsaved={load} />
  {/if}
  <Dialog bind:open={pickOpen} title={pickFor === "task" ? "New task" : "Log work"}>
    <form class="stack" onsubmit={picked}>
      <div class="field">
        <label for="pick-customer">Customer</label>
        <select id="pick-customer" class="input" required bind:value={pickId}>
          {#each customers as customer (customer.id)}<option value={customer.id}>{customer.name}</option>{/each}
        </select>
      </div>
      <div class="button-row end">
        <button class="button button-secondary" type="button" onclick={() => (pickOpen = false)}>Cancel</button>
        <button class="button button-primary" type="submit" disabled={busy}>Continue</button>
      </div>
    </form>
  </Dialog>
{:else if info}
  <main class="page-content">
    <div class="heading">
      <h1 class="title">Welcome, {info.user.display_name}</h1>
      {#if info.user.roles.length}
        <p class="small muted">{info.user.roles.map(roleName).join(", ")}</p>
      {/if}
    </div>
    <section class="empty">
      {#if info.user.roles.length}
        <p>There's no work here for your role.</p>
        <p class="small muted">All customers lists the customers that exist; the audit log is under Admin.</p>
      {:else}
        <p>You don't have a role yet.</p>
        <p class="small muted">Ask an administrator for one.</p>
      {/if}
    </section>
  </main>
{/if}

<style>
  .heading-row {
    display: flex;
    flex-wrap: wrap;
    align-items: flex-end;
    justify-content: space-between;
    gap: var(--space-3);
  }
  .heading {
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
  }
  .counts {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
    gap: var(--space-3);
    margin: 0;
  }
  .count {
    display: flex;
    flex-direction: column-reverse;
    justify-content: flex-end;
    gap: var(--space-1);
    padding: var(--space-3) var(--space-4);
    border: 1px solid var(--border);
    border-radius: var(--radius-md);
    background: var(--surface);
  }
  .count dt {
    color: var(--text-muted);
    font: var(--type-body-sm);
  }
  /* In the sans face: Marcellus draws 0 and 1 like the letters O and I. */
  .count dd {
    margin: 0;
    font: var(--type-heading);
    font-family: var(--font-sans);
    font-weight: 600;
    font-variant-numeric: tabular-nums;
  }
  .count.critical dd {
    color: var(--critical-text);
  }
  .count.warning dd {
    color: var(--warning-text);
  }
  /* Two panels to a row, each pair as tall as the taller one. */
  .panels {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: var(--space-4);
  }
  .panels.three {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
  .group-title {
    margin: var(--space-2) 0 0;
    font: var(--type-subheading);
  }
  .rows {
    display: flex;
    flex-direction: column;
    margin: 0;
    padding: 0;
    list-style: none;
  }
  .rows li {
    padding: var(--space-2) 0;
  }
  .rows li + li {
    border-top: 1px solid var(--border);
  }
  .task {
    display: flex;
    align-items: center;
    gap: var(--space-3);
  }
  .tick {
    display: inline-flex;
    flex-shrink: 0;
    align-items: center;
    justify-content: center;
    width: 24px;
    height: 24px;
    padding: 0;
    border: 2px solid var(--border-strong);
    border-radius: 50%;
    background: var(--surface);
    color: transparent;
    cursor: pointer;
  }
  .tick:hover,
  .tick:focus-visible {
    border-color: var(--ok-text);
    color: var(--ok-text);
  }
  .body {
    display: flex;
    flex: 1;
    flex-direction: column;
    gap: 2px;
    min-width: 0;
  }
  .line,
  .badges {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-2);
  }
  .when {
    display: flex;
    flex-shrink: 0;
    flex-direction: column;
    align-items: flex-end;
    gap: var(--space-1);
  }
  .needs,
  .recent {
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
  }
  .strong {
    font-weight: 600;
  }
  /* A row's own name leads to the thing itself: it reads as the name, and as a link
     when pointed at. */
  .what {
    color: var(--text);
    text-decoration: none;
  }
  .what:hover {
    text-decoration: underline;
  }
  .end {
    justify-content: flex-end;
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
  @media (max-width: 900px) {
    .panels,
    .panels.three {
      grid-template-columns: minmax(0, 1fr);
    }
  }
</style>
