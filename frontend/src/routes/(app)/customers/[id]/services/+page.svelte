<script lang="ts">
  import { page } from "$app/state";
  import { resolve } from "$app/paths";
  import Check from "@lucide/svelte/icons/check";
  import Gavel from "@lucide/svelte/icons/gavel";
  import Pencil from "@lucide/svelte/icons/pencil";
  import Plus from "@lucide/svelte/icons/plus";
  import RefreshCw from "@lucide/svelte/icons/refresh-cw";
  import Trash from "@lucide/svelte/icons/trash-2";
  import X from "@lucide/svelte/icons/x";
  import { api, ApiError, sessionGone } from "#lib/api.js";
  import { pageTitle } from "#lib/branding.svelte.js";
  import Dialog from "#lib/components/Dialog.svelte";
  import Pill from "#lib/components/Pill.svelte";
  import PlanningDialogs from "#lib/components/PlanningDialogs.svelte";
  import RowMenu from "#lib/components/RowMenu.svelte";
  import SideList from "#lib/components/SideList.svelte";
  import { sharedCustomer } from "#lib/context.js";
  import { SYSTEM_TYPES, type CaseKind, type CustomerDetail, type CustomerService } from "#lib/customers.js";
  import { date } from "#lib/format.js";
  import {
    decisionPill, dueTone, dueWords, forWhom as whoFor, renewalOpen, rhythm, today, warnLine,
  } from "#lib/planning.js";
  import { CASE_KINDS, showValue, type DetailField, type StandardService } from "#lib/services.js";
  import type { SideGroup } from "#lib/sidelist.js";
  import { toast } from "#lib/toast.svelte.js";
  import { LOG_KINDS, type LogEntry, type LogPage } from "#lib/worklog.js";

  // The customer's services, as in the mockup: a side list of active and ended
  // services, and the chosen one with its case number, details (the standard's,
  // ones added for this customer, and those not used here) and the systems it
  // covers. Managers add and change services; everyone reads them.
  const shared = sharedCustomer();
  const customer = $derived(shared.current);
  const services = $derived(customer?.services ?? []);
  const base = $derived(resolve("/(app)/customers/[id]/services", { id: String(customer?.id ?? "") }));
  const agreementsHref = $derived(resolve("/(app)/customers/[id]/agreements", { id: String(customer?.id ?? "") }));
  const wanted = $derived(Number(page.url.searchParams.get("service")) || null);
  const chosen = $derived(services.find((s) => s.id === wanted) ?? services[0] ?? null);
  const systemsById = $derived(new Map((customer?.systems ?? []).map((s) => [s.id, s])));
  const forWhom = $derived(chosen?.company_id
    ? customer?.companies?.find((c) => c.id === chosen.company_id)?.name ?? "one company"
    : "the whole group");

  const groups = $derived(([["active", "Active", "ok"], ["ended", "Ended", "critical"]] as const).map(
    ([status, label, tone]): SideGroup => ({
      label, tone,
      items: services.filter((s) => s.status === status).map((s) => ({
        id: s.id, label: s.name, href: `${base}?service=${s.id}`,
        note: status === "ended" ? `Ended ${date(s.ended_on)}` : s.agreement ? s.case_number || undefined : "No agreement",
        noteTone: status === "active" && !s.agreement ? "warning" as const : "muted" as const,
      })),
    })));

  // The Managers' form.
  type Value = string | number | boolean | null;
  // What's coming up on the chosen service: its recurring work, its other tasks and
  // its renewals, and the next of them.
  const now = today();
  let planning = $state<ReturnType<typeof PlanningDialogs>>();
  const tasks = $derived((customer?.tasks ?? []).filter((t) => t.service_id === chosen?.id));
  const recurring = $derived(tasks.filter((t) => t.every));
  const renewals = $derived((customer?.renewals ?? []).filter((r) => r.service_id === chosen?.id));
  const next = $derived([
    ...tasks.map((t) => ({ day: t.due_on, title: t.title })),
    ...renewals.filter((r) => renewalOpen(r, now)).map((r) => ({ day: r.renews_on, title: r.what })),
  ].sort((a, b) => a.day.localeCompare(b.day))[0] ?? null);

  // The newest work on the chosen service, from the work log.
  let work = $state<LogEntry[]>([]);
  $effect(() => {
    const [of, service] = [customer?.id, chosen?.id];
    void customer;
    if (of === undefined || service === undefined) return;
    let stale = false;
    api<LogPage>("GET", `/customers/${of}/log?period=all&limit=5&service_id=${service}`)
      .then((found) => !stale && (work = found.entries))
      .catch(() => !stale && (work = []));
    return () => (stale = true);
  });

  let catalog = $state<StandardService[]>([]);
  let open = $state(false);
  let removeOpen = $state(false);
  let error = $state<string | null>(null);
  let busy = $state(false);
  let draft = $state<{
    id: number | null; standard_service_id: number | null; status: "active" | "ended";
    started_on: string; ended_on: string; company_id: number | null;
    values: Record<string, Value>; not_used: string[];
    extra: { label: string; value: string }[];
    systems: Record<number, { on: boolean; note: string }>;
    case_number: string; case_kind: CaseKind; notes: string;
  } | null>(null);

  const standard = $derived(catalog.find((s) => s.id === draft?.standard_service_id) ?? null);
  const fields = $derived.by((): DetailField[] => {
    if (!draft) return [];
    if (draft.id === null) return standard?.details ?? [];
    const current = services.find((s) => s.id === draft?.id);
    return [...(current?.details.filter((d) => !d.added) ?? []), ...(current?.not_used.map((n) =>
      standard?.details.find((d) => d.key === n.key) ?? { ...n, kind: "text" as const, choices: [], help: "" }) ?? [])];
  });

  async function edit(found?: CustomerService) {
    error = null;
    try {
      catalog = await api<StandardService[]>("GET", "/services");
    } catch (e) {
      if (!sessionGone(e)) toast(e instanceof ApiError ? e.message : "The catalog could not be loaded.", "critical");
      return;
    }
    const systems = Object.fromEntries((customer?.systems ?? []).map((s) => {
      const covered = found?.systems.find((c) => c.system_id === s.id);
      return [s.id, { on: !!covered, note: covered?.note ?? "" }];
    }));
    draft = found ? {
      id: found.id, standard_service_id: found.standard_service_id, status: found.status,
      started_on: found.started_on ?? "", ended_on: found.ended_on ?? "", company_id: found.company_id,
      values: Object.fromEntries(found.details.filter((d) => !d.added).map((d) => [d.key, d.value])),
      not_used: found.not_used.map((n) => n.key),
      extra: found.details.filter((d) => d.added).map((d) => ({ label: d.label, value: d.value === null ? "" : String(d.value) })),
      systems, case_number: found.case_number, case_kind: found.case_kind, notes: found.notes,
    } : {
      id: null, standard_service_id: null, status: "active", started_on: "", ended_on: "", company_id: null,
      values: {}, not_used: [], extra: [], systems, case_number: "", case_kind: "", notes: "",
    };
    open = true;
  }

  function cleaned(field: DetailField, value: Value): Value {
    if (value === "" || value === null || value === undefined) return null;
    if (field.kind === "number") return Number(value);
    return value;
  }

  async function save(event: SubmitEvent) {
    event.preventDefault();
    if (!draft) return;
    const d = draft;
    const body = {
      standard_service_id: d.standard_service_id, status: d.status,
      started_on: d.started_on || null, ended_on: d.status === "ended" ? d.ended_on || null : null,
      company_id: d.company_id,
      values: Object.fromEntries(fields.filter((f) => !d.not_used.includes(f.key)).map((f) => [f.key, cleaned(f, d.values[f.key] ?? null)])),
      not_used: d.not_used,
      extra: d.extra.filter((e) => e.label.trim()).map((e) => ({ label: e.label, value: e.value || null })),
      systems: Object.entries(d.systems).filter(([, s]) => s.on).map(([id, s]) => ({ system_id: Number(id), note: s.note })),
      case_number: d.case_number.trim(), case_kind: d.case_kind, notes: d.notes,
    };
    busy = true;
    error = null;
    try {
      const url = `/customers/${customer?.id}/services`;
      const detail = await api<CustomerDetail>(d.id === null ? "POST" : "PUT", d.id === null ? url : `${url}/${d.id}`, body);
      shared.use(detail);
      open = false;
      toast("Service saved.", "ok", { key: "saved" });
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
      shared.use(await api<CustomerDetail>("DELETE", `/customers/${customer?.id}/services/${gone.id}`));
      toast(`${gone.name} is removed.`, "ok");
    } catch (e) {
      if (!sessionGone(e)) toast(e instanceof ApiError ? e.message : "Something went wrong.", "critical");
    }
  }
</script>

<svelte:head><title>{pageTitle(`Services · ${customer?.name ?? "Customer"}`)}</title></svelte:head>

{#if customer}
  {#if services.length}
    <div class="layout">
      <SideList label="{customer.name}'s services" {groups} selected={chosen?.id ?? null} filterLabel="Filter services">
        {#snippet footer()}
          {#if customer.may_manage}
            <button class="button button-secondary add" type="button" onclick={() => edit()}>
              <Plus size={16} aria-hidden="true" />Add a service
            </button>
          {/if}
        {/snippet}
      </SideList>

      {#if chosen}
        <div class="detail">
          <section class="section" aria-labelledby="service-title">
            <div class="title-row">
              <div class="names">
                <h2 class="service-name" id="service-title">{chosen.name}</h2>
                <p class="small muted">{customer.name} · from the standard service {chosen.name} · for {forWhom}</p>
                <div>
                  {#if chosen.status === "active"}
                    <Pill tone="ok" text={chosen.started_on ? `Active since ${date(chosen.started_on)}` : "Active"} />
                  {:else}
                    <Pill tone="critical" text="Ended {date(chosen.ended_on)}" />
                  {/if}
                </div>
              </div>
              {#if customer.may_manage}
                <div class="button-row">
                  <button class="button button-accent" type="button" onclick={() => edit(chosen ?? undefined)}>
                    <Pencil size={16} aria-hidden="true" />Change service
                  </button>
                  <RowMenu label="More for {chosen.name}" items={[
                    { label: "Remove service", icon: Trash, danger: true, run: () => (removeOpen = true) },
                  ]} />
                </div>
              {/if}
            </div>
            <div class="tiles">
              <div class="tile">
                <p class="label">Log time on</p>
                {#if chosen.case_number}
                  <span class="mono strong">{chosen.case_number}</span>
                  <span class="small muted">{chosen.case_kind ? `${CASE_KINDS[chosen.case_kind]} case` : "Case number"}{chosen.case_history.length ? ` · before: ${chosen.case_history.slice(0, 2).map((c) => c.number).join(", ")}` : ""}</span>
                {:else}
                  <span class="strong">No case number</span>
                  <span class="small muted">Each job needs a case number of its own.</span>
                {/if}
              </div>
              <div class="tile">
                <p class="label">Active agreement</p>
                {#if chosen.agreement}
                  <!-- eslint-disable-next-line svelte/no-navigation-without-resolve -- agreementsHref comes from resolve() -->
                  <a class="strong" href="{agreementsHref}?agreement={chosen.agreement.agreement_id}">{chosen.agreement.name}</a>
                  <span class="small muted">{chosen.agreement.section} · work on it is covered</span>
                {:else}
                  <Pill tone="warning" text="No agreement" />
                  <span class="small muted">Work on it is billable; ask a Manager.</span>
                {/if}
              </div>
              <div class="tile">
                <p class="label">What is up next</p>
                {#if next}
                  <span class="strong">{next.title}</span>
                  <span class="small muted">{date(next.day)} · <Pill tone={dueTone(next.day, now)} text={dueWords(next.day, now)} /></span>
                {:else}
                  <span class="strong">Nothing planned</span>
                  <span class="small muted">No tasks or renewals on this service.</span>
                {/if}
              </div>
            </div>
          </section>

          <section class="section" aria-labelledby="details-title">
            <h3 class="section-title" id="details-title">Details</h3>
            {#if chosen.details.length}
              <dl class="facts">
                {#each chosen.details as detail (detail.key)}
                  <dt>{detail.label}</dt>
                  <dd>
                    {showValue(detail, detail.value)}
                    {#if detail.added}<Pill tone="info" text="Added for {customer.name}" />{/if}
                    {#if detail.kept}<Pill tone="neutral" text="No longer in the standard" />{/if}
                  </dd>
                {/each}
              </dl>
            {:else}
              <p class="muted">No details.</p>
            {/if}
            {#if chosen.not_used.length}
              <p class="small muted">Not used here: {chosen.not_used.map((n) => n.label).join(", ")}.</p>
            {/if}
            {#if chosen.notes}<p class="notes">{chosen.notes}</p>{/if}
          </section>

          <section class="section" aria-labelledby="systems-title">
            <h3 class="section-title" id="systems-title">Systems it covers</h3>
            {#if chosen.systems.length}
              <div class="table-wrap">
                <table class="table">
                  <thead><tr><th>System</th><th>Role</th><th>Note for this service</th></tr></thead>
                  <tbody>
                    {#each chosen.systems as covered (covered.system_id)}
                      {@const system = systemsById.get(covered.system_id)}
                      <tr>
                        <td class="mono strong">{system?.name ?? "—"}</td>
                        <td class="muted">{system ? system.role || SYSTEM_TYPES[system.type] : ""}</td>
                        <td>{covered.note || "—"}</td>
                      </tr>
                    {/each}
                  </tbody>
                </table>
              </div>
            {:else}
              <p class="muted">No systems linked yet.</p>
            {/if}
          </section>

          <section class="section" aria-labelledby="recurring-title">
            <div class="heading-row">
              <h3 class="section-title" id="recurring-title">Recurring work</h3>
              {#if customer.may_edit && chosen.status === "active"}
                <button class="link-button" type="button"
                  onclick={() => planning?.newTask({ service_id: chosen?.id ?? null, every: { count: 3, unit: "months" } })}>
                  <Plus size={14} aria-hidden="true" />Add recurring work
                </button>
              {/if}
            </div>
            {#if recurring.length}
              <div class="table-wrap">
                <table class="table">
                  <thead><tr><th>What</th><th>How often</th><th>Next</th><th>For</th>{#if customer.may_edit}<th><span class="visually-hidden">Actions</span></th>{/if}</tr></thead>
                  <tbody>
                    {#each recurring as task (task.id)}
                      <tr>
                        <td><span class="strong">{task.title}</span>{#if task.notes}<br /><span class="small muted">{task.notes}</span>{/if}</td>
                        <td>{task.every ? rhythm(task.every) : ""}</td>
                        <td><span class="nowrap">{date(task.due_on)}</span> <Pill tone={dueTone(task.due_on, now)} text={dueWords(task.due_on, now)} /></td>
                        <td>{whoFor(task.audience, task.people)}</td>
                        {#if customer.may_edit}
                          <td class="actions">
                            <RowMenu label="Actions for “{task.title}”" items={[
                              { label: "Mark done", icon: Check, run: () => planning?.finishTask(task) },
                              { label: "Change task", icon: Pencil, run: () => planning?.changeTask(task) },
                              ...(task.may_remove ? [{ label: "Remove task", icon: Trash, danger: true, run: () => planning?.removeTask(task) }] : []),
                            ]} />
                          </td>
                        {/if}
                      </tr>
                    {/each}
                  </tbody>
                </table>
              </div>
            {:else}
              <p class="muted">Nothing recurs on this service yet, such as updates every three months or a restore test every six.</p>
            {/if}
            {#if tasks.length > recurring.length}
              <p class="small muted">
                {tasks.length - recurring.length === 1 ? "One other task" : `${tasks.length - recurring.length} other tasks`}
                on this service: see the <a href={resolve("/(app)/customers/[id]/timeline", { id: String(customer.id) })}>timeline</a>.
              </p>
            {/if}
          </section>

          <section class="section" aria-labelledby="renewals-title">
            <div class="heading-row">
              <h3 class="section-title" id="renewals-title">Renewals</h3>
              {#if customer.may_edit && chosen.status === "active"}
                <button class="link-button" type="button" onclick={() => planning?.newRenewal({ service_id: chosen?.id ?? null })}>
                  <Plus size={14} aria-hidden="true" />Add a renewal
                </button>
              {/if}
            </div>
            {#if renewals.length}
              <div class="table-wrap">
                <table class="table">
                  <thead><tr><th>What</th><th>Renews on</th><th>Decision</th><th>Warning</th>{#if customer.may_edit}<th><span class="visually-hidden">Actions</span></th>{/if}</tr></thead>
                  <tbody>
                    {#each renewals as renewal (renewal.id)}
                      <tr>
                        <td>
                          <span class="strong">{renewal.what}</span>
                          <br /><span class="small muted">{[renewal.every ? rhythm(renewal.every) : "Once", renewal.system, renewal.supplier].filter(Boolean).join(" · ")}</span>
                          {#if renewal.decision === "declined" && renewal.fallback}
                            <br /><span class="small">Before it runs out: {renewal.fallback}</span>
                          {/if}
                        </td>
                        <td class="nowrap">{date(renewal.renews_on)}</td>
                        <td><Pill {...decisionPill(renewal, now)} /></td>
                        <td class="small">{warnLine(renewal)}</td>
                        {#if customer.may_edit}
                          <td class="actions">
                            <RowMenu label="Actions for “{renewal.what}”" items={[
                              ...(renewal.decision === "renewed" ? [] : [{ label: "Mark as renewed", icon: RefreshCw, run: () => planning?.markRenewed(renewal) }]),
                              ...(customer.may_manage ? [{ label: "Record the decision", icon: Gavel, run: () => planning?.decideRenewal(renewal) }] : []),
                              { label: "Change renewal", icon: Pencil, run: () => planning?.changeRenewal(renewal) },
                              ...(customer.may_manage ? [{ label: "Remove renewal", icon: Trash, danger: true, run: () => planning?.removeRenewal(renewal) }] : []),
                            ]} />
                          </td>
                        {/if}
                      </tr>
                    {/each}
                  </tbody>
                </table>
              </div>
              <p class="small muted">Dates and decisions only: prices and the keys themselves aren't kept in Þing.</p>
            {:else}
              <p class="muted">Nothing on this service runs out on a date yet, such as a licence, a certificate or a warranty.</p>
            {/if}
          </section>

          <section class="section" aria-labelledby="work-title">
            <div class="heading-row">
              <h3 class="section-title" id="work-title">Work on this service</h3>
              <a class="small" href={resolve("/(app)/customers/[id]/log", { id: String(customer.id) })}>Work log</a>
            </div>
            {#if work.length}
              <ul class="work">
                {#each work as entry (entry.id)}
                  <li>
                    <time class="small muted mono" datetime={entry.happened_at}>{date(entry.happened_at)}</time>
                    <span class="work-body">
                      <span>{entry.text}</span>
                      <span class="small muted">{[entry.author, LOG_KINDS[entry.kind], entry.systems.join(", "), entry.case_number].filter(Boolean).join(" · ")}</span>
                    </span>
                  </li>
                {/each}
              </ul>
            {:else}
              <p class="muted">Nothing logged on this service yet.</p>
            {/if}
          </section>
        </div>
        <PlanningDialogs bind:this={planning} {customer} onchanged={shared.use} />
      {/if}
    </div>
  {:else}
    <section class="empty">
      <p>No services yet.</p>
      <p class="small muted">What we provide this customer, each copied from a standard service and made its own.</p>
      {#if customer.may_manage}
        <div><button class="button button-accent" type="button" onclick={() => edit()}>
          <Plus size={16} aria-hidden="true" />Add a service
        </button></div>
      {/if}
    </section>
  {/if}
{/if}

<Dialog bind:open title={draft?.id ? "Change service" : "Add a service"}>
  {#if open && draft}
    <form class="stack" onsubmit={save}>
      {#if error}<p class="alert alert-critical" role="alert">{error}</p>{/if}
      {#if draft.id === null}
        <div class="field">
          <label for="service-standard">Standard service</label>
          <select id="service-standard" class="input" required bind:value={draft.standard_service_id}>
            <option value={null} disabled>Choose one</option>
            {#each catalog as option (option.id)}<option value={option.id}>{option.name}</option>{/each}
          </select>
        </div>
      {/if}
      <div class="pair">
        <div class="field">
          <label for="service-status">Status</label>
          <select id="service-status" class="input" bind:value={draft.status}>
            <option value="active">Active</option><option value="ended">Ended</option>
          </select>
        </div>
        <div class="field">
          <label for="service-start">Active since</label>
          <input id="service-start" class="input" type="date" bind:value={draft.started_on} />
        </div>
        {#if draft.status === "ended"}
          <div class="field">
            <label for="service-end">Ended on</label>
            <input id="service-end" class="input" type="date" required bind:value={draft.ended_on} />
          </div>
        {/if}
      </div>
      {#if customer?.companies?.length}
        <div class="field">
          <label for="service-company">For</label>
          <select id="service-company" class="input" bind:value={draft.company_id}>
            <option value={null}>The whole group</option>
            {#each customer.companies as company (company.id)}<option value={company.id}>{company.name}</option>{/each}
          </select>
        </div>
      {/if}
      <div class="pair">
        <div class="field">
          <label for="service-case">Log time on (case number)</label>
          <input id="service-case" class="input mono" maxlength="30" bind:value={draft.case_number} />
        </div>
        <div class="field">
          <label for="service-case-kind">Kind of case</label>
          <select id="service-case-kind" class="input" bind:value={draft.case_kind}>
            <option value="">Not said</option>
            {#each Object.entries(CASE_KINDS) as [value, name] (value)}<option {value}>{name}</option>{/each}
          </select>
        </div>
      </div>

      {#if fields.length}
        <fieldset class="checks">
          <legend class="check-title">Details</legend>
          {#each fields as field (field.key)}
            {@const unused = draft.not_used.includes(field.key)}
            <div class="detail-field">
              <div class="field">
                <label for="value-{field.key}">{field.label}</label>
                {#if field.kind === "choice"}
                  <select id="value-{field.key}" class="input" disabled={unused} bind:value={draft.values[field.key]}>
                    <option value={null}>Not said</option>
                    {#each field.choices as choice (choice)}<option value={choice}>{choice}</option>{/each}
                  </select>
                {:else if field.kind === "yes_no"}
                  <select id="value-{field.key}" class="input" disabled={unused} bind:value={draft.values[field.key]}>
                    <option value={null}>Not known</option><option value={true}>Yes</option><option value={false}>No</option>
                  </select>
                {:else}
                  <input id="value-{field.key}" class="input" disabled={unused}
                    type={field.kind === "number" ? "number" : field.kind === "date" ? "date" : "text"}
                    bind:value={draft.values[field.key]} />
                {/if}
                {#if field.help}<span class="hint">{field.help}</span>{/if}
              </div>
              <label class="check small">
                <input type="checkbox" value={field.key} bind:group={draft.not_used} /><span>Not used here</span>
              </label>
            </div>
          {/each}
        </fieldset>
      {/if}

      <fieldset class="checks">
        <legend class="check-title">Added for this customer</legend>
        {#each draft.extra as extra, n (n)}
          <div class="extra-row">
            <input class="input" aria-label="Detail" placeholder="Detail" maxlength="80" bind:value={extra.label} />
            <input class="input" aria-label="Value" placeholder="Value" maxlength="1000" bind:value={extra.value} />
            <button class="icon-button" type="button" aria-label="Remove {extra.label || 'this detail'}"
              onclick={() => draft?.extra.splice(n, 1)}><X size={16} aria-hidden="true" /></button>
          </div>
        {/each}
        <div><button class="button button-secondary" type="button" onclick={() => draft?.extra.push({ label: "", value: "" })}>
          <Plus size={16} aria-hidden="true" />Add a detail
        </button></div>
      </fieldset>

      {#if customer?.systems?.length}
        <fieldset class="checks">
          <legend class="check-title">Systems it covers</legend>
          {#each customer.systems as system (system.id)}
            <div class="system-row">
              <label class="check"><input type="checkbox" bind:checked={draft.systems[system.id].on} /><span class="mono">{system.name}</span></label>
              {#if draft.systems[system.id].on}
                <input class="input" aria-label="Note for {system.name}" placeholder="Note for this service" maxlength="300"
                  bind:value={draft.systems[system.id].note} />
              {/if}
            </div>
          {/each}
        </fieldset>
      {/if}

      <div class="field">
        <label for="service-notes">Notes</label>
        <textarea id="service-notes" class="input" rows="2" maxlength="2000" bind:value={draft.notes}></textarea>
      </div>
      <div class="button-row end">
        <button class="button button-secondary" type="button" onclick={() => (open = false)}>Cancel</button>
        <button class="button button-primary" type="submit" disabled={busy}>Save service</button>
      </div>
    </form>
  {/if}
</Dialog>

<Dialog bind:open={removeOpen} title="Remove {chosen?.name ?? ''}">
  <p>For a service entered by mistake. One the customer had keeps its history: end it instead.</p>
  {#snippet actions()}
    <button class="button button-secondary" type="button" onclick={() => (removeOpen = false)}>Cancel</button>
    <button class="button button-primary" type="button" onclick={remove}>Remove service</button>
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
  .service-name {
    margin: 0;
    font-family: var(--font-display, Marcellus, Georgia, serif);
    font-size: 32px;
    font-weight: 400;
    line-height: 38px;
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
  .heading-row {
    display: flex;
    flex-wrap: wrap;
    align-items: baseline;
    justify-content: space-between;
    gap: var(--space-3);
  }
  .nowrap {
    white-space: nowrap;
  }
  .actions {
    width: 1%;
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
  }
  .work li + li {
    border-top: 1px solid var(--border);
  }
  .work-body {
    display: flex;
    flex-direction: column;
    gap: 2px;
    min-width: 0;
  }
  .pair {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
    gap: var(--space-3);
  }
  .detail-field {
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto;
    gap: var(--space-3);
    align-items: center;
  }
  .extra-row {
    display: grid;
    grid-template-columns: minmax(0, 1fr) minmax(0, 2fr) auto;
    gap: var(--space-2);
  }
  .system-row {
    display: grid;
    grid-template-columns: minmax(120px, auto) minmax(0, 1fr);
    gap: var(--space-2);
    align-items: center;
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
