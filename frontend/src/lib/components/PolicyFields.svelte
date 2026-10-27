<script lang="ts">
  // The security policy's fields, shared by the setup wizard and the admin panel.
  import type { SecuritySettings } from "#lib/policy.js";
  import Switch from "./Switch.svelte";

  type NumberField = Exclude<
    keyof SecuritySettings,
    "breach_check_enabled" | "require_mfa_everyone" | "require_mfa_administrators"
  >;

  // The same limits as backend/app/policy.py LIMITS; the server checks them too.
  const FIELDS: { key: NumberField; label: string; hint: string; min: number; max: number }[] = [
    {
      key: "min_password_length",
      label: "Minimum password length",
      hint: "Characters. Þing has no rules about character types: length and the breach check protect better (ASVS 6.2).",
      min: 8,
      max: 64,
    },
    {
      key: "lockout_threshold",
      label: "Lock an account after",
      hint: "Wrong passwords or codes in a row.",
      min: 3,
      max: 50,
    },
    {
      key: "lockout_minutes",
      label: "Keep it locked for",
      hint: "Minutes. An administrator can unlock it sooner.",
      min: 1,
      max: 1440,
    },
    {
      key: "idle_timeout_minutes",
      label: "Sign out after inactivity",
      hint: "Minutes without any activity.",
      min: 5,
      max: 720,
    },
    {
      key: "max_session_hours",
      label: "Sign out after at most",
      hint: "Hours, however active. People then sign in again.",
      min: 1,
      max: 72,
    },
  ];

  let { values = $bindable() }: { values: SecuritySettings } = $props();
  const uid = $props.id();
</script>

<div class="part">
  <fieldset class="group">
    <legend class="check-title">Multifactor authentication</legend>
    <p class="small muted">
      Something besides the password at every sign-in: an authenticator app, a passkey or a
      security key. A stolen password alone then isn't enough.
    </p>
    <Switch title="Required for everyone" bind:checked={values.require_mfa_everyone}>
      Everyone sets up an authenticator app, a passkey or a security key at their next sign-in.
    </Switch>
    <Switch
      title="Required for administrators"
      disabled={values.require_mfa_everyone}
      bind:checked={() => values.require_mfa_everyone || values.require_mfa_administrators,
        (on) => (values.require_mfa_administrators = on)}
    >
      {values.require_mfa_everyone
        ? "Included while everyone needs it."
        : "Administrators need it even when others don't."}
    </Switch>
    {#if !values.require_mfa_everyone}
      <p class="alert alert-warning">
        Þing holds customer data: OWASP ASVS Level 2 expects multifactor for everyone. The
        administrator made during setup always needs it.
      </p>
    {/if}
  </fieldset>
</div>

{#snippet number(key: NumberField)}
  {@const field = FIELDS.find((f) => f.key === key)!}
  <div class="field">
    <label for="{uid}-{field.key}">{field.label}</label>
    <input
      id="{uid}-{field.key}"
      class="input number"
      type="number"
      min={field.min}
      max={field.max}
      required
      aria-describedby="{uid}-{field.key}-hint"
      bind:value={values[field.key]}
    />
    <span class="hint" id="{uid}-{field.key}-hint">
      {field.hint} From {field.min} to {field.max}.
    </span>
  </div>
{/snippet}

<div class="part">
  <fieldset class="group">
    <legend class="check-title">Passwords</legend>
    <p class="small muted">
      Rules for new passwords. Passwords people already have keep working until they change them.
    </p>
    <Switch title="Check new passwords against known data breaches"
      bind:checked={values.breach_check_enabled}>
      Uses Have I Been Pwned, free and without an account. Only the first 5 characters of a hash
      of the password leave the server. Needs internet access to api.pwnedpasswords.com.
    </Switch>
    {@render number("min_password_length")}
  </fieldset>
</div>

<div class="part">
  <fieldset class="group">
    <legend class="check-title">Lockout</legend>
    <p class="small muted">
      Stops anyone guessing passwords or codes: after too many wrong tries in a row, the account
      is locked for a while.
    </p>
    {@render number("lockout_threshold")}
    {@render number("lockout_minutes")}
  </fieldset>
</div>

<div class="part">
  <fieldset class="group">
    <legend class="check-title">Sessions</legend>
    <p class="small muted">
      How long people stay signed in. Shorter is safer on shared computers; people are warned
      two minutes before an idle sign-out.
    </p>
    {@render number("idle_timeout_minutes")}
    {@render number("max_session_hours")}
  </fieldset>
</div>


<style>
  /* Each part set off by a line, as on the Network access settings. */
  .part {
    padding-top: var(--space-4);
    border-top: 1px solid var(--border);
  }
  .group {
    display: flex;
    flex-direction: column;
    gap: var(--space-4);
    margin: 0;
    padding: 0;
    border: 0;
  }
  .group legend {
    margin-bottom: var(--space-3);
  }
  .number {
    max-width: 10rem;
  }
</style>
