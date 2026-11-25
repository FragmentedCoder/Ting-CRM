<script lang="ts">
  import { api, ApiError, sessionGone } from "#lib/api.js";
  import type { CustomerDetail } from "#lib/customers.js";
  import { date } from "#lib/format.js";
  import {
    AUDIENCES, DECISIONS, REASONS, RENEWAL_KINDS, addDays, addInterval, emptyRenewal, emptyTask, momentOn,
    nextDue, rhythm, today,
    type Audience, type Decision, type Every, type Reason, type Renewal, type Task,
  } from "#lib/planning.js";
  import { toast } from "#lib/toast.svelte.js";
  import Dialog from "./Dialog.svelte";

  // The forms for what's coming up, the same wherever they're offered (the overview,
  // the timeline, a service): a task, ticking it off, a renewal, its decision, and
  // marking it renewed. What goes to the work log (done, decided, renewed) asks which
  // day it happened, today unless said, so what's recorded later lands on its own day.
  // A page keeps one of these and calls what it needs:
  //   <PlanningDialogs bind:this={planning} {customer} onchanged={shared.use} />
  //   planning.newTask({ service_id: 4 })
  let {
    customer,
    onchanged,
  }: {
    customer: CustomerDetail;
    /** The customer as it is after a change. */
    onchanged: (detail: CustomerDetail) => void;
  } = $props();

  type Mode = "task" | "finish" | "renewal" | "decide" | "renewed" | "remove-task" | "remove-renewal";
  let open = $state(false);
  let mode = $state<Mode>("task");
  let error = $state<string | null>(null);
  let busy = $state(false);

  // The task or renewal a form is about; none for a new one.
  let subject = $state<Task | null>(null);
  let renewal = $state<Renewal | null>(null);

  let task = $state(emptyTask());
  let draft = $state(emptyRenewal());
  let repeats = $state(false);
  let every = $state<Every>({ count: 3, unit: "months" });
  let note = $state("");
  // The day it happened: a task done, a renewal decided or renewed.
  let doneOn = $state(today());
  const next = $derived(mode === "finish" && subject && doneOn ? nextDue(subject, doneOn) : null);
  let decision = $state<Exclude<Decision, "renewed">>("");
  let reason = $state<Reason | "">("");
  let fallback = $state("");
  let fallbackDue = $state("");
  let nextOn = $state("");

  const services = $derived((customer.services ?? []).filter((s) =>
    s.status === "active" || s.id === task.service_id || s.id === draft.service_id));
  const systems = $derived((customer.systems ?? []).filter((s) =>
    !s.retired_on || s.id === task.system_id || s.id === draft.system_id));
  const colleagues = $derived(customer.colleagues ?? []);

  const TITLES: Record<Mode, () => string> = {
    task: () => (subject ? "Change task" : `New task for ${customer.name}`),
    finish: () => "Mark as done",
    renewal: () => (renewal ? "Change renewal" : `New renewal for ${customer.name}`),
    decide: () => "Renewal decision",
    renewed: () => "Mark as renewed",
    "remove-task": () => "Remove this task",
    "remove-renewal": () => "Remove this renewal",
  };

  function show(which: Mode) {
    mode = which;
    error = null;
    note = "";
    doneOn = today();
    open = true;
  }

  export function newTask(preset: Partial<ReturnType<typeof emptyTask>> = {}) {
    subject = null;
    task = { ...emptyTask(), ...preset };
    repeats = !!task.every;
    every = task.every ?? { count: 3, unit: "months" };
    show("task");
  }

  export function changeTask(found: Task) {
    subject = found;
    task = {
      title: found.title, notes: found.notes, due_on: found.due_on, audience: found.audience,
      people: found.people.map((p) => p.id), service_id: found.service_id, system_id: found.system_id,
      ticket: found.ticket, every: found.every,
    };
    repeats = !!found.every;
    every = found.every ? { ...found.every } : { count: 3, unit: "months" };
    show("task");
  }

  export function finishTask(found: Task) {
    subject = found;
    show("finish");
  }

  export function removeTask(found: Task) {
    subject = found;
    show("remove-task");
  }

  export function newRenewal(preset: Partial<ReturnType<typeof emptyRenewal>> = {}) {
    renewal = null;
    draft = { ...emptyRenewal(), ...preset };
    repeats = !!draft.every;
    every = draft.every ?? { count: 12, unit: "months" };
    show("renewal");
  }

  export function changeRenewal(found: Renewal) {
    renewal = found;
    draft = {
      what: found.what, kind: found.kind, renews_on: found.renews_on, every: found.every,
      warn_days: found.warn_days, audience: found.audience, people: [...found.people],
      service_id: found.service_id, system_id: found.system_id, supplier: found.supplier, notes: found.notes,
    };
    repeats = !!found.every;
    every = found.every ? { ...found.every } : { count: 12, unit: "months" };
    show("renewal");
  }

  export function decideRenewal(found: Renewal) {
    renewal = found;
    decision = found.decision === "renewed" ? "" : found.decision;
    reason = found.reason;
    fallback = found.fallback;
    fallbackDue = addDays(found.renews_on, -2);
    show("decide");
  }

  export function markRenewed(found: Renewal) {
    renewal = found;
    nextOn = found.every ? addInterval(found.renews_on, found.every) : "";
    show("renewed");
  }

  export function removeRenewal(found: Renewal) {
    renewal = found;
    show("remove-renewal");
  }

  async function send(method: "POST" | "PUT" | "DELETE", path: string, body: unknown, done: string) {
    busy = true;
    error = null;
    try {
      const detail = await api<CustomerDetail>(method, `/customers/${customer.id}${path}`, body);
      open = false;
      toast(done, "ok", { key: "saved" });
      onchanged(detail);
    } catch (e) {
      if (!sessionGone(e)) error = e instanceof ApiError ? e.message : "Something went wrong. Try again.";
    } finally {
      busy = false;
    }
  }

  const named = (audience: Audience, people: number[]) => (audience === "people" ? people : []);

  function save(event: SubmitEvent) {
    event.preventDefault();
    if (mode === "task") {
      const body = { ...task, people: named(task.audience, task.people), every: repeats ? every : null };
      void (subject ? send("PUT", `/tasks/${subject.id}`, body, "Task saved.") : send("POST", "/tasks", body, "Task added."));
    } else if (mode === "finish" && subject) {
      void send("POST", `/tasks/${subject.id}/done`, { note, done_on: doneOn, happened_at: momentOn(doneOn) },
        subject.every ? "Done. The next one is on the timeline." : "Done, and in the work log.");
    } else if (mode === "renewal") {
      const body = { ...draft, people: named(draft.audience, draft.people), every: repeats ? every : null };
      void (renewal ? send("PUT", `/renewals/${renewal.id}`, body, "Renewal saved.")
        : send("POST", "/renewals", body, "Renewal added."));
    } else if (mode === "decide" && renewal) {
      const declined = decision === "declined";
      void send("POST", `/renewals/${renewal.id}/decision`, {
        decision, reason: declined ? reason : "", fallback: declined ? fallback : "",
        fallback_due: declined && fallback.trim() && fallbackDue ? fallbackDue : null,
        decided_on: doneOn, happened_at: momentOn(doneOn),
      }, "Decision saved.");
    } else if (mode === "renewed" && renewal) {
      void send("POST", `/renewals/${renewal.id}/renewed`,
        { note, next_on: nextOn || null, renewed_on: doneOn, happened_at: momentOn(doneOn) }, "Marked as renewed.");
    }
  }

  function remove() {
    if (mode === "remove-task" && subject) void send("DELETE", `/tasks/${subject.id}`, undefined, "Task removed.");
    if (mode === "remove-renewal" && renewal) {
      void send("DELETE", `/renewals/${renewal.id}`, undefined, "Renewal removed.");
    }
  }
</script>

{#snippet rhythmFields(label: string, hint: string)}
  <div class="repeat">
    <label class="check"><input type="checkbox" bind:checked={repeats} /><span>{label}</span></label>
    {#if repeats}
      <div class="every">
        <label for="plan-count">Every</label>
        <input id="plan-count" class="input count" type="number" min="1" max="120" required bind:value={every.count} />
        <label for="plan-unit" class="visually-hidden">Weeks or months</label>
        <select id="plan-unit" class="input" bind:value={every.unit}>
          <option value="weeks">{every.count === 1 ? "week" : "weeks"}</option>
          <option value="months">{every.count === 1 ? "month" : "months"}</option>
        </select>
      </div>
      <span class="hint">{hint}</span>
    {/if}
  </div>
{/snippet}

{#snippet whoFields(label: string, value: { audience: Audience; people: number[] })}
  <div class="field">
    <label for="plan-audience">{label}</label>
    <select id="plan-audience" class="input" bind:value={value.audience}>
      {#each Object.entries(AUDIENCES) as [key, name] (key)}<option value={key}>{name}</option>{/each}
    </select>
  </div>
  {#if value.audience === "people"}
    <fieldset class="checks">
      <legend class="check-title">Who</legend>
      <div class="people">
        {#each colleagues as person (person.id)}
          <label class="check">
            <input type="checkbox" checked={value.people.includes(person.id)}
              onchange={(event) => (value.people = event.currentTarget.checked
                ? [...value.people, person.id] : value.people.filter((id) => id !== person.id))} />
            <span>{person.display_name}</span>
          </label>
        {/each}
      </div>
    </fieldset>
  {/if}
{/snippet}

{#snippet aboutFields(value: { service_id: number | null; system_id: number | null })}
  <div class="pair">
    <div class="field">
      <label for="plan-service">Service</label>
      <select id="plan-service" class="input" bind:value={value.service_id}>
        <option value={null}>None</option>
        {#each services as service (service.id)}<option value={service.id}>{service.name}</option>{/each}
      </select>
    </div>
    <div class="field">
      <label for="plan-system">System</label>
      <select id="plan-system" class="input" bind:value={value.system_id}>
        <option value={null}>None</option>
        {#each systems as system (system.id)}<option value={system.id}>{system.name}</option>{/each}
      </select>
    </div>
  </div>
{/snippet}

{#snippet buttons(label: string)}
  <div class="button-row end">
    <button class="button button-secondary" type="button" onclick={() => (open = false)}>Cancel</button>
    <button class="button button-primary" type="submit" disabled={busy}>{label}</button>
  </div>
{/snippet}

<Dialog bind:open title={TITLES[mode]()}>
  {#if open}
    {#if error}<p class="alert alert-critical" role="alert">{error}</p>{/if}
    {#if mode === "task"}
      <form class="stack" onsubmit={save}>
        <div class="field">
          <label for="plan-title">What needs doing</label>
          <input id="plan-title" class="input" required maxlength="200" bind:value={task.title} />
        </div>
        <div class="pair">
          <div class="field">
            <label for="plan-due">Due</label>
            <input id="plan-due" class="input" type="date" required bind:value={task.due_on} />
          </div>
          <div class="field">
            <label for="plan-ticket">Ticket ID</label>
            <input id="plan-ticket" class="input mono" maxlength="40" bind:value={task.ticket} />
          </div>
        </div>
        {@render whoFields("For", task)}
        {@render rhythmFields("It repeats", "Ticking it off schedules the next one, counted from the newest day it was done.")}
        {@render aboutFields(task)}
        <div class="field">
          <label for="plan-notes">Notes</label>
          <textarea id="plan-notes" class="input" rows="2" maxlength="2000" bind:value={task.notes}></textarea>
          <span class="hint">What to do, or what's special, such as “Also update the booking service on APP01”.</span>
        </div>
        {@render buttons(subject ? "Save task" : "Add task")}
      </form>
    {:else if mode === "finish" && subject}
      <form class="stack" onsubmit={save}>
        <p>“{subject.title}” goes to the work log as done, on the day it was done.</p>
        <div class="field">
          <label for="plan-done-on">Done on</label>
          <input id="plan-done-on" class="input" type="date" required max={today()} bind:value={doneOn} />
          <span class="hint">Today, or the earlier day it was done if you're recording it afterwards.</span>
        </div>
        <div class="field">
          <label for="plan-note">What was done</label>
          <textarea id="plan-note" class="input" rows="3" maxlength="2000" bind:value={note}></textarea>
          <span class="hint">Optional. Left empty, the work log says it's done.</span>
        </div>
        {#if subject.every && next}
          <p class="small muted">
            {rhythm(subject.every)}: the next one will be due {date(next.due)}{#if next.late}, counted from
              {date(next.late)}, the newest day it was done. An older time doesn't move it back{/if}.
          </p>
        {/if}
        {@render buttons("Mark done")}
      </form>
    {:else if mode === "renewal"}
      <form class="stack" onsubmit={save}>
        <div class="field">
          <label for="plan-what">What renews</label>
          <input id="plan-what" class="input" required maxlength="200" bind:value={draft.what} />
          <span class="hint">Such as “Firewall feature key”. Never the key itself: keys stay in the password manager.</span>
        </div>
        <div class="pair">
          <div class="field">
            <label for="plan-kind">Type</label>
            <select id="plan-kind" class="input" bind:value={draft.kind}>
              {#each Object.entries(RENEWAL_KINDS) as [key, name] (key)}<option value={key}>{name}</option>{/each}
            </select>
          </div>
          <div class="field">
            <label for="plan-renews">Renews on</label>
            <input id="plan-renews" class="input" type="date" required bind:value={draft.renews_on} />
          </div>
        </div>
        {@render rhythmFields("It renews again", "Marking it as renewed moves it to the next date.")}
        <div class="pair">
          {@render whoFields("Warn", draft)}
          <div class="field">
            <label for="plan-warn">Days before</label>
            <input id="plan-warn" class="input count" type="number" min="0" max="365" required bind:value={draft.warn_days} />
          </div>
        </div>
        {@render aboutFields(draft)}
        <div class="field">
          <label for="plan-supplier">Supplier</label>
          <input id="plan-supplier" class="input" maxlength="150" bind:value={draft.supplier} />
        </div>
        <div class="field">
          <label for="plan-renewal-notes">Notes</label>
          <textarea id="plan-renewal-notes" class="input" rows="2" maxlength="2000" bind:value={draft.notes}></textarea>
        </div>
        {@render buttons(renewal ? "Save renewal" : "Add renewal")}
      </form>
    {:else if mode === "decide" && renewal}
      <form class="stack" onsubmit={save}>
        <p>{renewal.what} renews on {date(renewal.renews_on)}.</p>
        <fieldset class="checks">
          <legend class="check-title">Decision</legend>
          <label class="check"><input type="radio" name="plan-decision" value="approved" bind:group={decision} />
            <span>{DECISIONS.approved}<span class="small muted">: the customer and a Manager agreed to renew it</span></span></label>
          <label class="check"><input type="radio" name="plan-decision" value="waiting" bind:group={decision} />
            <span>{DECISIONS.waiting}</span></label>
          <label class="check"><input type="radio" name="plan-decision" value="declined" bind:group={decision} />
            <span>{DECISIONS.declined}</span></label>
          <label class="check"><input type="radio" name="plan-decision" value="" bind:group={decision} />
            <span>No decision yet</span></label>
        </fieldset>
        {#if decision === "declined"}
          <div class="field">
            <label for="plan-reason">Why</label>
            <select id="plan-reason" class="input" required bind:value={reason}>
              <option value="" disabled>Choose a reason</option>
              {#each Object.entries(REASONS) as [key, name] (key)}<option value={key}>{name}</option>{/each}
            </select>
          </div>
          <div class="field">
            <label for="plan-fallback">What must be done before it runs out</label>
            <input id="plan-fallback" class="input" maxlength="300" bind:value={fallback} />
            <span class="hint">Such as “Switch off web filtering”. It becomes a task for the customer's technicians.</span>
          </div>
          {#if fallback.trim()}
            <div class="field">
              <label for="plan-fallback-due">Do it by</label>
              <input id="plan-fallback-due" class="input" type="date" bind:value={fallbackDue} />
            </div>
          {/if}
        {/if}
        {#if decision === "approved" || decision === "declined"}
          <div class="field">
            <label for="plan-decided-on">Decided on</label>
            <input id="plan-decided-on" class="input" type="date" required max={today()} bind:value={doneOn} />
            <span class="hint">It goes to the work log on this day.</span>
          </div>
        {/if}
        {@render buttons("Save decision")}
      </form>
    {:else if mode === "renewed" && renewal}
      <form class="stack" onsubmit={save}>
        <p>“{renewal.what}” was renewed. It goes to the work log, on the day it was renewed.</p>
        <div class="field">
          <label for="plan-renewed-on">Renewed on</label>
          <input id="plan-renewed-on" class="input" type="date" required max={today()} bind:value={doneOn} />
        </div>
        <div class="field">
          <label for="plan-next">Renews next on</label>
          <input id="plan-next" class="input" type="date" min={addDays(renewal.renews_on, 1)} bind:value={nextOn} />
          <span class="hint">{renewal.every ? `${rhythm(renewal.every)}, counted from ${date(renewal.renews_on)}, the date it ran to, whichever day it was renewed.`
            : "Leave it empty if it doesn't renew again."}</span>
        </div>
        <div class="field">
          <label for="plan-renewed-note">Note</label>
          <textarea id="plan-renewed-note" class="input" rows="2" maxlength="2000" bind:value={note}></textarea>
          <span class="hint">Optional, such as “Installed on FW01”.</span>
        </div>
        {@render buttons("Mark as renewed")}
      </form>
    {:else if mode === "remove-task" && subject}
      <p>“{subject.title}” is removed without going to the work log, and the removal is logged.</p>
      <div class="button-row end">
        <button class="button button-secondary" type="button" onclick={() => (open = false)}>Cancel</button>
        <button class="button button-primary" type="button" disabled={busy} onclick={remove}>Remove task</button>
      </div>
    {:else if mode === "remove-renewal" && renewal}
      <p>“{renewal.what}” is removed with its decision, and the removal is logged. What was logged about it stays in the work log.</p>
      <div class="button-row end">
        <button class="button button-secondary" type="button" onclick={() => (open = false)}>Cancel</button>
        <button class="button button-primary" type="button" disabled={busy} onclick={remove}>Remove renewal</button>
      </div>
    {/if}
  {/if}
</Dialog>

<style>
  .pair {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
    gap: var(--space-3);
    align-items: start;
  }
  .repeat {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
  }
  .every {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    font: var(--type-label);
  }
  .every select {
    width: auto;
  }
  .count {
    width: 6rem;
  }
  .hint {
    color: var(--text-muted);
    font: var(--type-body-sm);
  }
  .people {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2) var(--space-4);
  }
  .end {
    justify-content: flex-end;
  }
</style>
