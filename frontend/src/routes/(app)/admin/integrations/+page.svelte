<script lang="ts">
  import { onMount } from "svelte";
  import { api, ApiError, sessionGone } from "#lib/api.js";
  import { pageTitle } from "#lib/branding.svelte.js";
  import type { CvrSettings } from "#lib/cvr.js";
  import { withStepUp } from "#lib/stepUp.svelte.js";
  import { toast } from "#lib/toast.svelte.js";

  // Þing's calls out to other services about customers: today the CVR lookup.
  let form = $state<CvrSettings | null>(null);
  let error = $state<string | null>(null);
  let busy = $state(false);

  onMount(async () => {
    try {
      form = await api<CvrSettings>("GET", "/admin/integrations/cvr");
    } catch (e) {
      if (!sessionGone(e)) error = e instanceof ApiError ? e.message : "Not available.";
    }
  });

  async function save(event: SubmitEvent) {
    event.preventDefault();
    if (!form) return;
    busy = true;
    error = null;
    try {
      const body = form;
      form = await withStepUp(() => api<CvrSettings>("PUT", "/admin/integrations/cvr", body));
      toast(form.enabled ? "The CVR lookup is on." : "The CVR lookup is off.", "ok", { key: "saved" });
    } catch (e) {
      if (e instanceof ApiError && e.reason === "step_up_cancelled") return;
      if (!sessionGone(e)) error = e instanceof ApiError ? e.message : "Something went wrong. Try again.";
    } finally {
      busy = false;
    }
  }
</script>

<svelte:head><title>{pageTitle("Integrations · Admin")}</title></svelte:head>

<div class="page-header">
  <div>
    <h1 class="title">Integrations</h1>
    <p class="small muted">
      The services Þing calls out to about customers. Nothing reaches into Þing from outside.
    </p>
  </div>
</div>

{#if error}<p class="alert alert-critical" role="alert">{error}</p>{/if}

{#if form}
  <form class="section stack" onsubmit={save} aria-labelledby="cvr-title">
    <h2 class="section-title" id="cvr-title">CVR lookup</h2>
    <p class="small muted">
      Fills in a company's name and address from its CVR number, through cvrapi.dk, when
      someone adding or changing a customer asks for it. Only the number or name they typed is
      sent. cvrapi.dk allows 50 free lookups a day; Þing keeps each answer for a day, so the same
      number doesn't use another.
    </p>
    <label class="check">
      <input type="checkbox" bind:checked={form.enabled} />
      <span>Look up companies in the CVR register</span>
    </label>
    <div class="field contact">
      <label for="cvr-contact">Contact person for cvrapi.dk</label>
      <input id="cvr-contact" class="input" maxlength="150" required={form.enabled}
        aria-describedby="cvr-contact-hint" bind:value={form.contact} />
      <span class="hint" id="cvr-contact-hint">
        A name and a work email or phone, such as “Henrik Dahl it@nordlys.example”. cvrapi.dk
        asks every caller to say who they are; it's sent with each lookup, with your company's
        name.
      </span>
    </div>
    <div class="button-row">
      <button class="button button-primary" type="submit" disabled={busy}>Save</button>
    </div>
    <p class="small muted">Switching it on asks you to confirm it's you.</p>
  </form>
{/if}

<style>
  .contact {
    max-width: 420px;
  }
</style>
