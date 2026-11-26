<script lang="ts">
  import { api, ApiError, sessionGone } from "#lib/api.js";
  import { coveredOn, type CustomerDetail } from "#lib/customers.js";
  import { date } from "#lib/format.js";
  import { today } from "#lib/planning.js";
  import { toast } from "#lib/toast.svelte.js";
  import { LOGGED_KINDS, LOG_KINDS, toLocalInput, type LogEntry, type LogKind } from "#lib/worklog.js";
  import Dialog from "./Dialog.svelte";

  // Log work on a customer, the same everywhere it's offered: what was done, when,
  // and optionally the service and systems it was about, the case number the time
  // goes on, whether it was on site, and a ticket ID. Choosing a service fills in its
  // case number, and says whether an agreement covers the work: the one that ran on
  // the day the work was done, which needn't be today.
  let {
    open = $bindable(),
    customer,
    entry = null,
    onsaved,
  }: {
    open: boolean;
    customer: CustomerDetail;
    /** An entry to change; none to log a new one. */
    entry?: LogEntry | null;
    onsaved?: (saved: LogEntry) => void;
  } = $props();

  const services = $derived((customer.services ?? []).filter((s) => s.status === "active" || s.id === entry?.service_id));
  const systems = $derived((customer.systems ?? []).filter((s) => !s.retired_on || entry?.system_ids.includes(s.id)));

  let kind = $state<LogKind>("work");
  let happened = $state("");
  let text = $state("");
  let serviceId = $state<number | null>(null);
  let systemIds = $state<number[]>([]);
  let caseNumber = $state("");
  let onSite = $state(false);
  let ticket = $state("");
  let error = $state<string | null>(null);
  let busy = $state(false);
  let wasOpen = false;
  // The latest "When" can be: now. Work that hasn't happened yet can't be logged.
  let latest = $state(toLocalInput(new Date()));

  // Each time it opens: the entry's values, or a fresh one for now.
  $effect(() => {
    if (open && !wasOpen) {
      kind = entry?.kind ?? "work";
      happened = toLocalInput(entry ? new Date(entry.happened_at) : new Date());
      latest = toLocalInput(new Date());
      text = entry?.text ?? "";
      serviceId = entry?.service_id ?? null;
      systemIds = [...(entry?.system_ids ?? [])];
      caseNumber = entry?.case_number ?? "";
      onSite = entry?.on_site ?? false;
      ticket = entry?.ticket ?? "";
      error = null;
    }
    wasOpen = open;
  });

  function serviceChosen() {
    caseNumber = services.find((s) => s.id === serviceId)?.case_number ?? "";
  }

  // The day the work was done, in the person's own time, and what covered the
  // service then.
  const day = $derived(happened.slice(0, 10));
  const covering = $derived(serviceId !== null && day
    ? coveredOn(customer.agreements ?? [], serviceId, day) : null);

  async function save(event: SubmitEvent) {
    event.preventDefault();
    if (new Date(happened).getTime() > Date.now() + 60_000) {
      error = "Work can't be logged ahead of time: it's logged once it's done. Plan ahead with a task.";
      return;
    }
    busy = true;
    error = null;
    const body = {
      kind, text, happened_at: new Date(happened).toISOString(), happened_on: day, service_id: serviceId,
      system_ids: systemIds, case_number: caseNumber.trim(), on_site: onSite, ticket,
    };
    try {
      const base = `/customers/${customer.id}/log`;
      const saved = await api<LogEntry>(entry ? "PUT" : "POST", entry ? `${base}/${entry.id}` : base, body);
      open = false;
      toast(entry ? "Entry saved." : "Work logged.", "ok", { key: "saved" });
      onsaved?.(saved);
    } catch (e) {
      if (!sessionGone(e)) error = e instanceof ApiError ? e.message : "Something went wrong. Try again.";
    } finally {
      busy = false;
    }
  }
</script>

<Dialog bind:open title={entry ? "Change log entry" : `Log work on ${customer.name}`}>
  {#if open}
    <form class="stack" onsubmit={save}>
      {#if error}<p class="alert alert-critical" role="alert">{error}</p>{/if}
      <div class="field">
        <label for="log-text">What was done</label>
        <textarea id="log-text" class="input" rows="3" required maxlength="2000" bind:value={text}></textarea>
        <span class="hint">Plain text, such as “Added a 5G backup router on the firewall's port 3 as failover”.</span>
      </div>
      <div class="pair">
        <div class="field">
          <label for="log-kind">Type</label>
          <select id="log-kind" class="input" bind:value={kind}>
            {#each LOGGED_KINDS as value (value)}<option {value}>{LOG_KINDS[value]}</option>{/each}
            {#if !LOGGED_KINDS.includes(kind)}<option value={kind}>{LOG_KINDS[kind]}</option>{/if}
          </select>
        </div>
        <div class="field">
          <label for="log-when">When</label>
          <input id="log-when" class="input" type="datetime-local" required max={latest}
            onfocus={() => (latest = toLocalInput(new Date()))} bind:value={happened} />
        </div>
      </div>
      <div class="pair">
        <div class="field">
          <label for="log-service">Service</label>
          <select id="log-service" class="input" bind:value={serviceId} onchange={serviceChosen}>
            <option value={null}>None</option>
            {#each services as service (service.id)}<option value={service.id}>{service.name}</option>{/each}
          </select>
          {#if serviceId !== null && day}
            <span class="hint" class:billable={!covering}>
              {#if covering}
                Covered by {covering.name}.
              {:else if day === today()}
                No agreement covers it: the work is billable.
              {:else}
                No agreement covered it on {date(day)}: the work is billable.
              {/if}
            </span>
          {/if}
        </div>
        <div class="field">
          <label for="log-case">Log time on (case number)</label>
          <input id="log-case" class="input mono" maxlength="30" bind:value={caseNumber} />
        </div>
      </div>
      {#if systems.length}
        <fieldset class="checks">
          <legend class="check-title">Systems</legend>
          <div class="systems">
            {#each systems as system (system.id)}
              <label class="check"><input type="checkbox" value={system.id} bind:group={systemIds} /><span class="mono">{system.name}</span></label>
            {/each}
          </div>
        </fieldset>
      {/if}
      <div class="pair">
        <label class="check"><input type="checkbox" bind:checked={onSite} /><span>On site</span></label>
        <div class="field">
          <label for="log-ticket">Ticket ID</label>
          <input id="log-ticket" class="input mono" maxlength="40" bind:value={ticket} />
        </div>
      </div>
      <div class="button-row end">
        <button class="button button-secondary" type="button" onclick={() => (open = false)}>Cancel</button>
        <button class="button button-primary" type="submit" disabled={busy}>{entry ? "Save entry" : "Log work"}</button>
      </div>
    </form>
  {/if}
</Dialog>

<style>
  .pair {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
    gap: var(--space-3);
    align-items: start;
  }
  .systems {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2) var(--space-4);
  }
  .billable {
    color: var(--warning-text);
  }
  .end {
    justify-content: flex-end;
  }
</style>
