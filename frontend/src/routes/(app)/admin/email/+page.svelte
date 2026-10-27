<script lang="ts">
  import { onMount } from "svelte";
  import { api, ApiError, sessionGone } from "#lib/api.js";
  import { pageTitle } from "#lib/branding.svelte.js";
  import MailFields from "#lib/components/MailFields.svelte";
  import { mailBody, type MailServer, type MailStatus } from "#lib/mail.js";
  import { withStepUp } from "#lib/stepUp.svelte.js";
  import { toast } from "#lib/toast.svelte.js";

  // The mail server Þing sends reports and notices through.
  let status = $state<MailStatus | null>(null);
  let form = $state<MailServer | null>(null);
  let password = $state("");
  let to = $state("");
  let error = $state<string | null>(null);
  let busy = $state(false);
  let sending = $state(false);

  function use(found: MailStatus) {
    status = found;
    form = { ...found.server };
    password = "";
  }

  onMount(async () => {
    try {
      use(await api<MailStatus>("GET", "/admin/email"));
    } catch (e) {
      if (!sessionGone(e)) error = e instanceof ApiError ? e.message : "Not available.";
    }
  });

  async function save(event: SubmitEvent) {
    event.preventDefault();
    if (!form) return;
    busy = true;
    try {
      use(await withStepUp(() => api<MailStatus>("PUT", "/admin/email", mailBody(form!, password))));
      toast("Email settings saved.", "ok", { key: "saved" });
    } catch (e) {
      if (e instanceof ApiError && e.reason === "step_up_cancelled") return;
      if (!sessionGone(e)) toast(e instanceof ApiError ? e.message : "Something went wrong.", "critical");
    } finally {
      busy = false;
    }
  }

  async function sendTest(event: SubmitEvent) {
    event.preventDefault();
    sending = true;
    try {
      await api("POST", "/admin/email/test", { to });
      toast(`Test message sent to ${to}.`, "ok");
    } catch (e) {
      if (!sessionGone(e)) toast(e instanceof ApiError ? e.message : "Something went wrong.", "critical");
    } finally {
      sending = false;
    }
  }
</script>

<svelte:head><title>{pageTitle("Email · Admin")}</title></svelte:head>

<div class="page-header">
  <div>
    <h1 class="title">Email</h1>
    <p class="small muted">
      The mail server Þing sends reports and notices through. Its certificate is always
      checked. Every Administrator with an email address hears about each break-glass sign-in,
      each restore test, and backups that keep failing.
    </p>
  </div>
</div>

{#if error}<p class="alert alert-critical" role="alert">{error}</p>{/if}

{#if status && form}
  <form class="section stack" onsubmit={save} aria-labelledby="server-title">
    <h2 class="section-title" id="server-title">How mail goes out</h2>
    <MailFields bind:server={form} bind:password passwordSet={status.password_set} />
    <div class="button-row">
      <button class="button button-primary" type="submit" disabled={busy}>Save</button>
    </div>
    <p class="small muted">Changing the server, user name or password asks you to confirm it's you.</p>
  </form>

  <form class="section stack" onsubmit={sendTest} aria-labelledby="test-title">
    <h2 class="section-title" id="test-title">Send a test message</h2>
    <p class="small muted">With what's saved, to see that mail gets through.</p>
    <div class="field test-to">
      <label for="test-to">Send it to</label>
      <input id="test-to" class="input" type="email" required autocomplete="email" bind:value={to} />
    </div>
    <div class="button-row">
      <button class="button button-secondary" type="submit"
        disabled={sending || !status.server.host}>Send test message</button>
    </div>
  </form>
{/if}

<style>
  .test-to {
    max-width: 360px;
  }
</style>
