<script lang="ts">
  import { onMount } from "svelte";
  import { api, ApiError } from "#lib/api.js";
  import { pageTitle } from "#lib/branding.svelte.js";
  import Command from "#lib/components/Command.svelte";
  import PolicyFields from "#lib/components/PolicyFields.svelte";
  import Switch from "#lib/components/Switch.svelte";
  import {
    parseAddresses,
    securitySettings,
    type AdminSecurity,
    type SecuritySettings,
  } from "#lib/policy.js";
  import { withStepUp } from "#lib/stepUp.svelte.js";
  import { toast } from "#lib/toast.svelte.js";

  const RESET_COMMAND = "sudo ting admin reset-allowlist";

  let values = $state<SecuritySettings | null>(null);
  let lists = $state({ admin: "", login: "", adminOn: false, loginOn: false });
  let yourAddress = $state<string | null>(null);
  let error = $state<string | null>(null);
  let busy = $state(false);

  function use(security: AdminSecurity) {
    values = securitySettings(security);
    lists = {
      admin: security.admin_allowlist.join("\n"),
      login: security.login_allowlist.join("\n"),
      adminOn: security.admin_allowlist_enabled,
      loginOn: security.login_allowlist_enabled,
    };
    yourAddress = security.your_address;
  }

  onMount(async () => {
    try {
      use(await api<AdminSecurity>("GET", "/admin/security"));
    } catch (e) {
      error = e instanceof ApiError ? e.message : "Not available.";
    }
  });

  async function save(event: SubmitEvent) {
    event.preventDefault();
    if (!values) return;
    busy = true;
    error = null;
    const body = {
      ...values,
      admin_allowlist_enabled: lists.adminOn,
      admin_allowlist: parseAddresses(lists.admin),
      login_allowlist_enabled: lists.loginOn,
      login_allowlist: parseAddresses(lists.login),
    };
    try {
      use(await withStepUp(() => api<AdminSecurity>("PUT", "/admin/security", body)));
      toast("Security settings saved.", "ok", { key: "saved" });
    } catch (e) {
      if (e instanceof ApiError && e.reason === "step_up_cancelled") return;
      error = e instanceof ApiError ? e.message : "The settings could not be saved.";
    } finally {
      busy = false;
    }
  }
</script>

<svelte:head><title>{pageTitle("Security · Admin")}</title></svelte:head>

<div class="page-header">
  <div>
    <h1 class="title">Security</h1>
    <p class="small muted">
      Multifactor, passwords, lockout, sessions, and where Þing can be used from. Changes
      apply straight away.
    </p>
  </div>
</div>

{#if error}<p class="alert alert-critical" role="alert">{error}</p>{/if}

{#if values}
  <form class="stack" onsubmit={save}>
    <section class="section" aria-labelledby="sign-in-title">
      <h2 class="section-title" id="sign-in-title">Sign-in and sessions</h2>
      <p class="small muted">
        Who must use multifactor, what new passwords need, and how long people stay signed in.
        Lowering any of these asks you to confirm it's you, every time.
      </p>
      <div class="stack form-narrow">
        <PolicyFields bind:values />
      </div>
    </section>

    <section class="section" aria-labelledby="network-title">
      <h2 class="section-title" id="network-title">Network access</h2>
      <p class="small muted">
        Limit where Þing can be used from, by IP address or range. Both lists stay off until
        you switch them on.
      </p>
      <p class="small muted" id="address-hint">
        One address or range per line, such as 10.20.0.0/24. Your address right now:
        <span class="mono">{yourAddress ?? "unknown"}</span>. Þing won't save a list that leaves
        it out, so you can't lock yourself out.
      </p>

      <div class="network stack form-narrow">
        <h3 class="check-title">Signing in</h3>
        <Switch title="Only allow sign-in from these addresses" bind:checked={lists.loginOn}>
          Off: people can sign in from anywhere. On: only from these addresses, and anyone
          signed in elsewhere is signed out at their next click.
        </Switch>
        <div class="field">
          <label for="login-allowlist">Sign-in allowlist</label>
          <textarea id="login-allowlist" class="input mono" rows="4" spellcheck="false"
            aria-describedby="address-hint" bind:value={lists.login}></textarea>
        </div>
      </div>

      <div class="network stack form-narrow">
        <h3 class="check-title">The admin panel</h3>
        <Switch title="Only open the admin panel from these addresses" bind:checked={lists.adminOn}>
          Administrators elsewhere can still sign in and work, but the admin panel and its link
          are hidden from them.
        </Switch>
        <div class="field">
          <label for="admin-allowlist">Admin panel allowlist</label>
          <textarea id="admin-allowlist" class="input mono" rows="4" spellcheck="false"
            aria-describedby="address-hint" bind:value={lists.admin}></textarea>
        </div>
      </div>

      <div class="stack form-narrow">
        <p class="small">
          If an allowlist ever locks every administrator out, run this on the server. It
          switches both allowlists off and keeps their addresses.
        </p>
        <Command command={RESET_COMMAND} />
      </div>
    </section>

    <div>
      <button class="button button-primary" type="submit" disabled={busy}>Save settings</button>
    </div>
  </form>
{/if}

<style>
  .network {
    padding-top: var(--space-4);
    border-top: 1px solid var(--border);
  }
</style>
