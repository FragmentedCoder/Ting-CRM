<script lang="ts">
  import { onMount } from "svelte";
  import { api, ApiError, sessionGone } from "#lib/api.js";
  import { pageTitle } from "#lib/branding.svelte.js";
  import Switch from "#lib/components/Switch.svelte";
  import { AHEAD_MONTHS, aheadWords, general, loadGeneral, useGeneral, type General } from "#lib/general.svelte.js";
  import { codeChoices } from "#lib/phone.js";
  import { can, session } from "#lib/session.svelte.js";
  import { toast } from "#lib/toast.svelte.js";

  // How Þing behaves for the whole team. Administrators set it all; how far ahead
  // what's coming up reaches is the Managers' too, since the warnings are theirs.
  const administers = $derived(can(session.current, "administer"));

  let form = $state<General>({ ...general.current });
  let loaded = $state(false);
  let error = $state<string | null>(null);
  let busy = $state(false);

  onMount(async () => {
    await loadGeneral(true);
    form = { ...general.current };
    loaded = true;
  });

  async function save(event: SubmitEvent) {
    event.preventDefault();
    busy = true;
    error = null;
    try {
      useGeneral(administers
        ? await api<General>("PUT", "/general", form)
        : await api<General>("PUT", "/general/warnings", { warn_ahead_months: form.warn_ahead_months }));
      form = { ...general.current };
      toast("Settings saved.", "ok", { key: "saved" });
    } catch (e) {
      if (!sessionGone(e)) error = e instanceof ApiError ? e.message : "Something went wrong. Try again.";
    } finally {
      busy = false;
    }
  }
</script>

<svelte:head><title>{pageTitle("General · Admin")}</title></svelte:head>

<div class="page-header">
  <div>
    <h1 class="title">General</h1>
    <p class="small muted">
      How Þing behaves for the whole team.
      {#if !administers}Managers set how far ahead it looks; the rest is the Administrators'.{/if}
    </p>
  </div>
</div>

{#if loaded}
  <form class="stack" onsubmit={save}>
    {#if error}<p class="alert alert-critical" role="alert">{error}</p>{/if}

    <section class="section" aria-labelledby="ahead-title">
      <h2 class="section-title" id="ahead-title">Looking ahead</h2>
      <div class="field form-narrow">
        <label for="general-ahead">Show what's coming up for the next</label>
        <select id="general-ahead" class="input" bind:value={form.warn_ahead_months}>
          {#each AHEAD_MONTHS as months (months)}
            <option value={months}>{months === 12 ? "1 year" : aheadWords(months)}</option>
          {/each}
        </select>
        <span class="hint">
          Renewals, recurring work, tasks and notice days due within this show on My work and on
          a customer's overview, with their warnings: in 5 days, in 63 days, overdue. What's
          further off stays on the timeline and on its service, without a warning, until it
          comes within reach.
        </span>
      </div>
    </section>

    {#if administers}
      <section class="section" aria-labelledby="log-title">
        <h2 class="section-title" id="log-title">Work log</h2>
        <Switch title="Mark work ticked off from a task as Covered or Billable" bind:checked={form.cover_ticked_off_work}>
          Like work logged by hand: Covered when an agreement that ran on the day it was done
          covers its service, Billable when none did. Off, only work logged by hand is marked.
        </Switch>
      </section>

      <section class="section" aria-labelledby="customers-title">
        <h2 class="section-title" id="customers-title">Customers</h2>
        <Switch title="Show Getting started on a new customer" bind:checked={form.getting_started}>
          The steps on a customer's overview until its contacts and sites are added and someone
          is chosen to work with it.
        </Switch>
      </section>

      <section class="section" aria-labelledby="phone-title">
        <h2 class="section-title" id="phone-title">Phone numbers</h2>
        <div class="field form-narrow">
          <label for="general-code">Country code offered first</label>
          <select id="general-code" class="input" bind:value={form.phone_country_code}>
            {#each codeChoices(form.phone_country_code) as choice (choice.code)}
              <option value={choice.code}>{choice.code}{choice.name ? ` ${choice.name}` : ""}</option>
            {/each}
          </select>
          <span class="hint">Where a phone number is typed, such as a contact's, this one is chosen to begin with.</span>
        </div>
      </section>
    {/if}

    <div><button class="button button-primary" type="submit" disabled={busy}>Save settings</button></div>
  </form>
{/if}
