<script lang="ts">
  import { onDestroy, onMount } from "svelte";
  import { api, ApiError, sessionGone } from "#lib/api.js";
  import { pageTitle } from "#lib/branding.svelte.js";
  import Command from "#lib/components/Command.svelte";
  import TlsFields from "#lib/components/TlsFields.svelte";
  import { dateTime } from "#lib/format.js";
  import { withStepUp } from "#lib/stepUp.svelte.js";
  import {
    choiceFrom,
    expiry,
    MODES,
    RESET_COMMAND,
    tlsBody,
    type TlsChoice,
    type TlsStatus,
  } from "#lib/tls.js";
  import { toast } from "#lib/toast.svelte.js";

  // Which certificate Þing serves. Caddy takes a change within a few seconds;
  // the page then asks again to show what's served.
  let status = $state<TlsStatus | null>(null);
  let choice = $state<TlsChoice | null>(null);
  let error = $state<string | null>(null);
  let busy = $state(false);
  let timer: ReturnType<typeof setTimeout> | undefined;

  async function load() {
    try {
      status = await api<TlsStatus>("GET", "/admin/tls");
    } catch (e) {
      if (!sessionGone(e)) error = e instanceof ApiError ? e.message : "Not available.";
    }
  }

  onMount(async () => {
    await load();
    if (status) choice = choiceFrom(status);
  });
  onDestroy(() => clearTimeout(timer));

  async function save(event: SubmitEvent) {
    event.preventDefault();
    if (!choice) return;
    busy = true;
    try {
      status = await withStepUp(() => api<TlsStatus>("PUT", "/admin/tls", tlsBody(choice!)));
      choice = choiceFrom(status);
      toast("Certificate settings saved. Caddy takes them within a few seconds.", "ok", { key: "saved" });
      clearTimeout(timer);
      timer = setTimeout(load, 8000);
    } catch (e) {
      if (e instanceof ApiError && e.reason === "step_up_cancelled") return;
      if (!sessionGone(e)) toast(e instanceof ApiError ? e.message : "Something went wrong.", "critical");
    } finally {
      busy = false;
    }
  }
</script>

<svelte:head><title>{pageTitle("Certificate · Admin")}</title></svelte:head>

<div class="page-header">
  <div>
    <h1 class="title">Certificate</h1>
    <p class="small muted">The certificate browsers see at {status?.host ?? "Þing's address"}.</p>
  </div>
</div>

{#if error}<p class="alert alert-critical" role="alert">{error}</p>{/if}

{#if status && choice}
  <section class="section" aria-labelledby="served-title">
    <h2 class="section-title" id="served-title">Serving now</h2>
    <dl class="facts">
      <dt>Chosen</dt>
      <dd>{MODES.find((option) => option.mode === status!.settings.mode)?.name}</dd>
      {#if status.served}
        <dt>Certificate</dt>
        <dd>{status.served.subject}, from {status.served.issuer}</dd>
        <dt>Valid until</dt>
        <dd>
          {dateTime(status.served.not_after)} ({expiry(status.served)}){status.settings.mode === "own"
            ? ""
            : ". Caddy renews it on its own"}
        </dd>
      {:else}
        <dt>Certificate</dt>
        <dd>Caddy didn't answer just now.</dd>
      {/if}
    </dl>
    {#if status.root_url}
      <p class="small">
        Each computer that uses Þing trusts this authority once its root certificate is
        installed (on Windows, in Trusted Root Certification Authorities).
        <!-- eslint-disable-next-line svelte/no-navigation-without-resolve -- a file Caddy serves, not a page -->
        <a href={status.root_url} download="ting-root.crt">Download the root certificate</a>
      </p>
    {/if}
  </section>

  <form class="section stack" onsubmit={save} aria-labelledby="choice-title">
    <h2 class="section-title" id="choice-title">Change it</h2>
    <TlsFields bind:choice host={status.host} uploaded={status.settings.certificate} resetHint={false}
      tokenSet={status.cloudflare_token_set} keySet={status.rfc2136_key_set} />
    <div class="button-row">
      <button class="button button-primary" type="submit" disabled={busy}>Save</button>
    </div>
    <p class="small muted">
      Saving asks you to confirm it's you. If Þing can't be reached after a change, run this
      on the server to go back to its own authority:
    </p>
    <Command command={RESET_COMMAND} />
  </form>
{/if}
