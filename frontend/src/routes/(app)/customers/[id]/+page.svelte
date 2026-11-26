<script lang="ts">
  import { resolve } from "$app/paths";
  import Circle from "@lucide/svelte/icons/circle";
  import CircleCheck from "@lucide/svelte/icons/circle-check";
  import Pin from "@lucide/svelte/icons/pin";
  import Plus from "@lucide/svelte/icons/plus";
  import TriangleAlert from "@lucide/svelte/icons/triangle-alert";
  import X from "@lucide/svelte/icons/x";
  import { api, ApiError, sessionGone } from "#lib/api.js";
  import { pageTitle } from "#lib/branding.svelte.js";
  import ContactCard from "#lib/components/ContactCard.svelte";
  import Dialog from "#lib/components/Dialog.svelte";
  import LogWorkDialog from "#lib/components/LogWorkDialog.svelte";
  import PlanningDialogs from "#lib/components/PlanningDialogs.svelte";
  import { sharedCustomer } from "#lib/context.js";
  import Pill from "#lib/components/Pill.svelte";
  import {
    PINS_PER_CUSTOMER, SYSTEM_TYPES, caseNumbers, currentVersion, pinnedLine, servicePill, supportLevel,
    systemsPreview,
    type CustomerDetail, type CustomerService, type Pin as PinRecord,
  } from "#lib/customers.js";
  import { aheadUntil, aheadWords } from "#lib/general.svelte.js";
  import { decisionPill, dueTone, dueWords, today } from "#lib/planning.js";
  import { CASE_KINDS, showValue } from "#lib/services.js";
  import { TIMELINE_TYPES, shortDay, timelineItems } from "#lib/timeline.js";
  import { LOG_KINDS, type LogEntry } from "#lib/worklog.js";
  import { date, dateTime } from "#lib/format.js";
  import { toast } from "#lib/toast.svelte.js";

  // A customer at a glance: the pinned warnings first, then who decides, who to talk
  // to and who works with it. Services, case numbers, systems and the work log join
  // it as Phase 2 adds them.
  const shared = sharedCustomer();
  const customer = $derived(shared.current);
  const id = $derived(String(customer?.id ?? ""));
  const pins = $derived(customer?.pins ?? []);
  const decider = $derived(customer?.contacts?.find((c) => c.roles.includes("decision_maker")) ?? null);
  const services = $derived(customer?.services ?? []);
  const support = $derived(supportLevel(services));
  // The systems at a glance: hosts with their virtual machines under them.
  const systems = $derived(systemsPreview(customer?.systems ?? [], 8));
  const cases = $derived(caseNumbers(services));

  // What's coming up: the next tasks, renewals and agreement dates, the soonest
  // (and what's overdue) first.
  const now = today();
  let planning = $state<ReturnType<typeof PlanningDialogs>>();
  const planned = $derived(customer
    ? timelineItems(customer, [], now).filter((item) => item.state !== "done").reverse() : []);
  // As far ahead as the team looks: what's further off waits on the timeline.
  const until = $derived(aheadUntil(now));
  const coming = $derived(planned.filter((item) => item.day <= until));
  const later = $derived(planned.length - coming.length);
  const COMING_SHOWN = 6;

  // Logging work: one line straight from the overview, or the full form.
  let logOpen = $state(false);
  let quick = $state("");
  let logging = $state(false);

  async function refresh() {
    const detail = await api<CustomerDetail>("GET", `/customers/${customer?.id}`).catch(() => null);
    if (detail) shared.use(detail);
  }

  async function logQuick(event: SubmitEvent) {
    event.preventDefault();
    if (!quick.trim() || !customer) return;
    logging = true;
    try {
      await api<LogEntry>("POST", `/customers/${customer.id}/log`, { kind: "work", text: quick });
      quick = "";
      toast("Work logged.", "ok", { key: "saved" });
      await refresh();
    } catch (e) {
      if (!sessionGone(e)) toast(e instanceof ApiError ? e.message : "Something went wrong.", "critical");
    } finally {
      logging = false;
    }
  }

  // A service at a glance: its first details filled in.
  function atThisCustomer(service: CustomerService): string {
    const filled = service.details.filter((d) => d.value !== null && d.value !== "");
    return filled.slice(0, 2).map((d) => showValue(d, d.value)).join("; ") || "—";
  }

  // Managers and Administrators pin up to three one-line warnings.
  let pinOpen = $state(false);
  let pinDraft = $state<{ id: number | null; text: string; severity: PinRecord["severity"] }>(
    { id: null, text: "", severity: "caution" });
  let pinError = $state<string | null>(null);
  let busy = $state(false);

  function editPin(found?: PinRecord) {
    pinDraft = found ? { id: found.id, text: found.text, severity: found.severity }
      : { id: null, text: "", severity: "caution" };
    pinError = null;
    pinOpen = true;
  }

  async function run(action: () => Promise<CustomerDetail>, done: string) {
    busy = true;
    pinError = null;
    try {
      shared.use(await action());
      pinOpen = false;
      toast(done, "ok", { key: "saved" });
    } catch (e) {
      if (sessionGone(e)) return;
      const message = e instanceof ApiError ? e.message : "Something went wrong. Try again.";
      if (pinOpen) pinError = message;
      else toast(message, "critical");
    } finally {
      busy = false;
    }
  }

  function savePin(event: SubmitEvent) {
    event.preventDefault();
    const { id: pinId, ...body } = pinDraft;
    const base = `/customers/${customer?.id}/pins`;
    run(() => pinId === null ? api("POST", base, body) : api("PUT", `${base}/${pinId}`, body),
      pinId === null ? "Warning pinned." : "Warning saved.");
  }

  function unpin(found: PinRecord) {
    run(() => api("DELETE", `/customers/${customer?.id}/pins/${found.id}`), "Warning unpinned.");
  }

  // For administrators, until a new customer is ready for work.
  const steps = $derived(customer ? [
    { label: "Add its contacts and sites", done: !!(customer.contacts?.length || customer.sites?.length),
      href: resolve("/(app)/customers/[id]/contacts", { id }) },
    { label: "Choose who works with it", done: !!customer.assigned?.length,
      href: resolve("/(app)/customers/[id]/people", { id }) },
  ] : []);
  const gettingStarted = $derived(!!customer?.may_manage && steps.some((step) => !step.done));
</script>

<svelte:head><title>{pageTitle(customer?.name ?? "Customer")}</title></svelte:head>

{#if customer}
  {#if pins.length || customer.may_manage}
    <div class="pins" role="note" aria-label="Pinned warnings">
      <div class="pins-head">
        <span class="small muted one-line">{pins.length ? pinnedLine(pins) : "No pinned warnings"}</span>
        {#if customer.may_manage && pins.length < PINS_PER_CUSTOMER}
          <button class="link-button" type="button" onclick={() => editPin()}>
            <Plus size={14} aria-hidden="true" />Pin a warning
          </button>
        {/if}
      </div>
      {#each pins as pin (pin.id)}
        <div class="pin {pin.severity}">
          {#if pin.severity === "critical"}
            <TriangleAlert size={18} aria-hidden="true" />
          {:else}
            <Pin size={18} aria-hidden="true" />
          {/if}
          <span class="visually-hidden">{pin.severity === "critical" ? "Hard rule:" : "Caution:"}</span>
          {#if customer.may_manage}
            <button class="pin-text one-line" type="button" title="Change this warning" onclick={() => editPin(pin)}>{pin.text}</button>
            <button class="icon-button unpin" type="button" aria-label="Unpin “{pin.text}”" title="Unpin"
              disabled={busy} onclick={() => unpin(pin)}><X size={16} aria-hidden="true" /></button>
          {:else}
            <span class="pin-text one-line" title={pin.text}>{pin.text}</span>
          {/if}
        </div>
      {/each}
    </div>
  {/if}

  <div class="tiles" aria-label="At a glance">
    <div class="tile">
      <p class="small muted label">Support</p>
      <Pill tone={support.tone} text={support.text} />
      {#if support.hours}<span class="small">{support.hours}</span>{/if}
    </div>
    <div class="tile">
      <p class="small muted label">Log time on</p>
      {#each cases as found (found.number)}
        <span class="case"><span class="mono strong">{found.number}</span>
          <span class="small">{found.services.join(", ")}</span>
          {#if found.kind}<Pill tone="info" text={CASE_KINDS[found.kind]} />{/if}</span>
      {:else}
        <span class="small muted">No case numbers yet.</span>
      {/each}
    </div>
    <div class="tile">
      <p class="small muted label">Decision-maker</p>
      {#if decider}
        <ContactCard contact={decider} inset />
      {:else}
        <span class="small muted">Nobody is marked as the decision-maker.</span>
      {/if}
    </div>
  </div>

  {#if services.length}
    <section class="section services" aria-labelledby="services-title">
      <div class="heading-row">
        <h2 class="section-title" id="services-title">Services</h2>
        <a class="small" href={resolve("/(app)/customers/[id]/services", { id })}>All details</a>
      </div>
      <div class="chips" aria-label="Services we provide">
        {#each services as service (service.id)}
          <Pill {...servicePill(service)} />
        {/each}
      </div>
      <div class="table-wrap">
        <table class="table">
          <thead><tr><th>Service</th><th>At this customer</th><th>Log time on</th><th>Agreement</th></tr></thead>
          <tbody>
            {#each services.filter((s) => s.status === "active") as service (service.id)}
              <tr>
                <td class="strong">{service.name}</td>
                <td>{atThisCustomer(service)}</td>
                <td class="mono">{service.case_number || "—"}</td>
                <td>
                  {#if service.agreement}
                    <Pill tone="ok" text={service.agreement.name} />
                  {:else}
                    <Pill tone="warning" text="No agreement" />
                  {/if}
                </td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    </section>
  {/if}

  {#if customer.agreements?.length}
    <section class="section services" aria-labelledby="agreements-title">
      <div class="heading-row">
        <h2 class="section-title" id="agreements-title">Agreements</h2>
        <a class="small" href={resolve("/(app)/customers/[id]/agreements", { id })}>All agreements</a>
      </div>
      <ul class="agreements">
        {#each customer.agreements.filter((a) => a.status !== "ended") as agreement (agreement.id)}
          {@const signed = currentVersion(agreement)?.signed_on}
          <li>
            <span class="agreement-top">
              <span class="strong">{agreement.name}</span>
              <Pill tone={agreement.status === "active" ? "ok" : "warning"}
                text={agreement.status === "active" ? "Active" : "Waiting for the customer"} />
            </span>
            <span class="small muted">
              {[signed ? `Signed ${date(signed)}` : null,
                `covers ${new Set(agreement.sections.map((s) => s.service_id).filter((s) => s !== null)).size} of ${services.filter((s) => s.status === "active").length} services`,
                agreement.ends_on ? `${agreement.auto_renews ? "renews" : "ends"} ${date(agreement.ends_on)}` : null,
                agreement.notice_by ? `notice by ${date(agreement.notice_by)}` : null].filter(Boolean).join(" · ")}
            </span>
          </li>
        {/each}
      </ul>
      {#if services.some((s) => s.status === "active" && !s.agreement)}
        <p class="alert alert-warning">
          {services.filter((s) => s.status === "active" && !s.agreement).map((s) => s.name).join(", ")}:
          no agreement yet.
        </p>
      {/if}
    </section>
  {/if}

  <section class="section services" aria-labelledby="work-title">
    <div class="heading-row">
      <h2 class="section-title" id="work-title">Latest work</h2>
      <a class="small" href={resolve("/(app)/customers/[id]/log", { id })}>All work logged</a>
    </div>
    {#if customer.may_edit}
      <form class="quick" onsubmit={logQuick}>
        <label class="visually-hidden" for="quick-log">Log work</label>
        <input id="quick-log" class="input" maxlength="2000" bind:value={quick}
          placeholder="What did you do? For example: replaced the switch in the server room" />
        <button class="button button-primary" type="submit" disabled={logging || !quick.trim()}>Log work</button>
        <button class="button button-secondary" type="button" onclick={() => (logOpen = true)}>More…</button>
      </form>
    {/if}
    {#if customer.latest_work?.length}
      <ul class="work">
        {#each customer.latest_work as entry (entry.id)}
          <li>
            <time class="small muted mono" datetime={entry.happened_at}>{date(entry.happened_at)}</time>
            <span class="work-body">
              <span>{entry.text}</span>
              <span class="small muted">
                {[entry.author, LOG_KINDS[entry.kind], entry.service, entry.case_number || null].filter(Boolean).join(" · ")}
              </span>
            </span>
          </li>
        {/each}
      </ul>
    {:else}
      <p class="muted">Nothing logged yet.</p>
    {/if}
  </section>
  <LogWorkDialog bind:open={logOpen} {customer} onsaved={refresh} />

  <section class="section services" aria-labelledby="coming-title">
    <div class="heading-row">
      <h2 class="section-title" id="coming-title">Coming up</h2>
      <span class="coming-actions">
        <a class="small" href={resolve("/(app)/customers/[id]/timeline", { id })}>Timeline</a>
        {#if customer.may_edit}
          <button class="button button-accent" type="button" onclick={() => planning?.newTask()}>
            <Plus size={16} aria-hidden="true" />New task
          </button>
        {/if}
      </span>
    </div>
    {#if coming.length}
      <ul class="coming">
        {#each coming.slice(0, COMING_SHOWN) as item (item.key)}
          <li>
            <span class="coming-when">
              <span class="small mono">{shortDay(item.day)}</span>
              <Pill tone={dueTone(item.day, now)} text={dueWords(item.day, now)} />
            </span>
            <span class="work-body">
              <span class="coming-title">
                <Pill tone="info" text={TIMELINE_TYPES[item.type]} />
                {#if item.renewal}<Pill {...decisionPill(item.renewal, now, until)} />{/if}
                <span>{item.title}</span>
              </span>
              {#if item.detail}<span class="small muted">{item.detail}</span>{/if}
            </span>
            {#if customer.may_edit && item.task}
              {@const task = item.task}
              <button class="button button-secondary" type="button" onclick={() => planning?.finishTask(task)}>Mark done</button>
            {/if}
          </li>
        {/each}
      </ul>
      {#if coming.length > COMING_SHOWN || later}
        <p class="small muted">
          {[coming.length > COMING_SHOWN ? `${coming.length - COMING_SHOWN} more` : null,
            later ? `${later} further off than the next ${aheadWords()}` : null].filter(Boolean).join(", and ")}
          on the timeline.
        </p>
      {/if}
    {:else if later}
      <p class="muted">Nothing in the next {aheadWords()}; {later} further off on the timeline.</p>
    {:else}
      <p class="muted">Nothing planned.</p>
    {/if}
  </section>
  <PlanningDialogs bind:this={planning} {customer} onchanged={shared.use} />

  <section class="section services" aria-labelledby="systems-title">
    <div class="heading-row">
      <h2 class="section-title" id="systems-title">Systems</h2>
      <a class="small" href={resolve("/(app)/customers/[id]/systems", { id })}>
        {systems.total ? `All ${systems.total}` : "Systems"}
      </a>
    </div>
    {#if systems.rows.length}
      <ul class="systems">
        {#each systems.rows as { system, guest, host } (system.id)}
          <li class:guest>
            <span class="system-name">
              <span class="mono strong">{system.name}</span>
              {#if host}<Pill tone="neutral" text="Host" />{/if}
              {#if system.type === "virtual_machine"}<Pill tone="info" text="VM" />{/if}
            </span>
            <span class="small muted">{system.role || SYSTEM_TYPES[system.type]}</span>
          </li>
        {/each}
      </ul>
    {:else}
      <p class="muted">No systems recorded yet.</p>
    {/if}
  </section>

  <div class="grid">
    {#if gettingStarted}
      <section class="section wide" aria-labelledby="start-title">
        <h2 class="section-title" id="start-title">Getting started</h2>
        <ol class="steps">
          {#each steps as step (step.label)}
            <li class:done={step.done}>
              {#if step.done}
                <CircleCheck size={18} aria-hidden="true" />
                <span>{step.label}<span class="visually-hidden">: done</span></span>
              {:else}
                <Circle size={18} aria-hidden="true" />
                <!-- eslint-disable-next-line svelte/no-navigation-without-resolve -- each step's href comes from resolve() -->
                <a href={step.href}>{step.label}</a>
              {/if}
            </li>
          {/each}
        </ol>
      </section>
    {/if}

    <section class="section" aria-labelledby="contacts-title">
      <h2 class="section-title" id="contacts-title">Contacts</h2>
      {#if customer.contacts?.length}
        <ul class="plain">
          {#each customer.contacts.slice(0, 4) as contact (contact.id)}
            <li>
              <span class="check-title">{contact.name}</span>
              <span class="small muted">{[contact.role, contact.email, contact.phone].filter(Boolean).join(" · ")}</span>
            </li>
          {/each}
        </ul>
      {:else}
        <p class="muted">No contacts yet.</p>
      {/if}
      <a class="small" href={resolve("/(app)/customers/[id]/contacts", { id })}>Contacts and sites</a>
    </section>

    <section class="section" aria-labelledby="people-title">
      <h2 class="section-title" id="people-title">People on this customer</h2>
      {#if customer.assigned?.length}
        <ul class="plain">
          {#each customer.assigned as person (person.id)}
            <li><span class="check-title">{person.display_name}</span></li>
          {/each}
        </ul>
      {:else}
        <p class="muted">Nobody is assigned yet.</p>
      {/if}
      <a class="small" href={resolve("/(app)/customers/[id]/people", { id })}>People</a>
    </section>

    <section class="section wide" aria-labelledby="facts-title">
      <h2 class="section-title" id="facts-title">Details</h2>
      <dl class="facts">
        <dt>Address</dt>
        <dd class="address">{customer.address || "—"}</dd>
        {#if customer.companies?.length}
          <dt>Group companies</dt>
          <dd>{customer.companies.map((c) => c.name).join(", ")}</dd>
        {/if}
        <dt>Sites</dt>
        <dd>{customer.sites?.map((s) => s.name).join(", ") || "—"}</dd>
        <dt>Records kept</dt>
        <dd>{customer.retention_months} months after it stops being a customer</dd>
        <dt>Added</dt>
        <dd>{dateTime(customer.created_at)}</dd>
      </dl>
      <p class="small muted">
        Everything here is encrypted with this customer's own key.
      </p>
    </section>
  </div>
{/if}

<Dialog bind:open={pinOpen} title={pinDraft.id === null ? "Pin a warning" : "Change pinned warning"}>
  <form class="stack" onsubmit={savePin}>
    {#if pinError}<p class="alert alert-critical" role="alert">{pinError}</p>{/if}
    <div class="field">
      <label for="pin-text">Warning</label>
      <input id="pin-text" class="input" required maxlength="120" bind:value={pinDraft.text} />
      <span class="hint">One short line every technician sees first, such as “Do not update in working hours”.</span>
    </div>
    <fieldset class="checks">
      <legend class="check-title">Kind</legend>
      <label class="check"><input type="radio" value="critical" bind:group={pinDraft.severity} /><span>A hard rule (red)</span></label>
      <label class="check"><input type="radio" value="caution" bind:group={pinDraft.severity} /><span>A caution (yellow)</span></label>
    </fieldset>
    <div class="button-row end">
      <button class="button button-secondary" type="button" onclick={() => (pinOpen = false)}>Cancel</button>
      <button class="button button-primary" type="submit" disabled={busy}>
        {pinDraft.id === null ? "Pin warning" : "Save warning"}
      </button>
    </div>
  </form>
</Dialog>

<style>
  .tiles {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
    gap: var(--space-3);
    margin-bottom: var(--space-4);
  }
  .tile {
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    gap: var(--space-2);
    padding: var(--space-3) var(--space-4);
    border: 1px solid var(--border);
    border-radius: var(--radius-md);
    background: var(--surface);
  }
  .tile > :global(.person) {
    align-self: stretch;
  }
  .case {
    display: flex;
    flex-wrap: wrap;
    align-items: baseline;
    gap: var(--space-2);
  }
  .strong {
    font-weight: 600;
  }
  .services {
    margin-bottom: var(--space-4);
  }
  .heading-row {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: var(--space-3);
  }
  .systems {
    display: flex;
    flex-direction: column;
    margin: 0;
    padding: 0;
    list-style: none;
  }
  .systems li {
    display: flex;
    flex-wrap: wrap;
    align-items: baseline;
    justify-content: space-between;
    gap: var(--space-1) var(--space-3);
    padding: var(--space-2) 0;
  }
  .systems li + li {
    border-top: 1px solid var(--border);
  }
  /* A virtual machine sits under its host. */
  .systems .guest {
    padding-left: var(--space-6);
  }
  .system-name {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-2);
  }
  .coming-actions {
    display: flex;
    align-items: center;
    gap: var(--space-4);
  }
  .coming {
    display: flex;
    flex-direction: column;
    margin: 0;
    padding: 0;
    list-style: none;
  }
  .coming li {
    display: grid;
    grid-template-columns: minmax(9rem, auto) minmax(0, 1fr) auto;
    gap: var(--space-3);
    align-items: center;
    padding: var(--space-2) 0;
  }
  .coming li + li {
    border-top: 1px solid var(--border);
  }
  .coming-when {
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    gap: var(--space-1);
  }
  .coming-title {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-2);
  }
  @media (max-width: 640px) {
    .coming li {
      grid-template-columns: minmax(0, 1fr);
    }
  }
  .quick {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2);
    margin: var(--space-2) 0;
  }
  .quick .input {
    flex: 1 1 260px;
    min-width: 0;
  }
  .work {
    display: flex;
    flex-direction: column;
    margin: 0;
    padding: 0;
    list-style: none;
  }
  .work li {
    display: grid;
    grid-template-columns: 6.5rem minmax(0, 1fr);
    gap: var(--space-3);
    padding: var(--space-2) 0;
    border-top: 1px solid var(--border);
  }
  .work-body {
    display: flex;
    flex-direction: column;
    gap: 2px;
    min-width: 0;
  }
  .agreements {
    display: flex;
    flex-direction: column;
    margin: var(--space-2) 0;
    padding: 0;
    list-style: none;
  }
  .agreements li {
    display: flex;
    flex-direction: column;
    gap: 2px;
    padding: var(--space-2) 0;
    border-top: 1px solid var(--border);
  }
  .agreement-top {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-2);
  }
  .chips {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2);
    margin: var(--space-2) 0 var(--space-3);
  }
  .pins {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    margin-bottom: var(--space-4);
  }
  .pins-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-3);
    min-width: 0;
  }
  .pins-head .link-button {
    display: inline-flex;
    flex-shrink: 0;
    align-items: center;
    gap: var(--space-1);
  }
  .pin {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    min-width: 0;
    padding: var(--space-2) var(--space-3);
    border-radius: var(--radius-md);
    font-weight: 500;
  }
  .pin :global(svg) {
    flex-shrink: 0;
  }
  .critical {
    background: var(--critical-bg);
    color: var(--critical-text);
  }
  .caution {
    background: var(--warning-bg);
    color: var(--warning-text);
  }
  .pin-text {
    flex: 1 1 auto;
    min-width: 0;
    padding: 0;
    border: 0;
    background: none;
    color: inherit;
    font: inherit;
    text-align: left;
  }
  button.pin-text {
    cursor: pointer;
  }
  .unpin {
    flex-shrink: 0;
    color: inherit;
  }
  .one-line {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .label {
    margin: 0;
  }
  .end {
    justify-content: flex-end;
  }
  .grid {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: var(--space-4);
  }
  .wide {
    grid-column: 1 / -1;
  }
  .steps {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    margin: 0;
    padding: 0;
    list-style: none;
  }
  .steps li {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    color: var(--text-muted);
  }
  .steps .done {
    color: var(--ok-text);
  }
  .steps .done span {
    color: var(--text-muted);
    text-decoration: line-through;
  }
  .plain {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    margin: 0;
    padding: 0;
    list-style: none;
  }
  .plain li {
    display: flex;
    flex-direction: column;
  }
  .address {
    white-space: pre-line;
  }
  @media (max-width: 760px) {
    .grid {
      grid-template-columns: minmax(0, 1fr);
    }
  }
</style>
