<script lang="ts">
  import KeyRound from "@lucide/svelte/icons/key-round";
  import Smartphone from "@lucide/svelte/icons/smartphone";
  import { api, ApiError } from "#lib/api.js";
  import CodeInput from "./CodeInput.svelte";
  import { browserSupportsWebAuthn, passkeyErrorMessage, registerPasskey } from "#lib/passkeys.js";
  import { groupSecret, qrPath } from "#lib/qr.js";
  import { sessionEnded, type SecondFactorResult } from "#lib/session.svelte.js";

  let { onDone }: { onDone: (result: SecondFactorResult) => void } = $props();
  const uid = $props.id();

  let step = $state<"choose" | "app">("choose");
  let enrolment = $state<{ secret: string; otpauth_uri: string } | null>(null);
  let code = $state("");
  let error = $state<string | null>(null);
  let busy = $state(false);

  const passkeysWork = browserSupportsWebAuthn();
  const qr = $derived(enrolment ? qrPath(enrolment.otpauth_uri) : null);

  async function attempt<T>(action: () => Promise<T>): Promise<T | null> {
    busy = true;
    error = null;
    try {
      return await action();
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) {
        await sessionEnded(e.message, e.reason ?? "");
        return null;
      }
      error = e instanceof ApiError ? e.message : passkeyErrorMessage(e);
      return null;
    } finally {
      busy = false;
    }
  }

  async function choosePasskey() {
    const result = await attempt(() => registerPasskey("Passkey"));
    if (result) onDone(result);
  }

  async function chooseApp() {
    enrolment = await attempt(() => api("POST", "/auth/mfa/totp/enrol"));
    if (enrolment) step = "app";
  }

  async function confirmApp(event: SubmitEvent) {
    event.preventDefault();
    const result = await attempt(() =>
      api<SecondFactorResult>("POST", "/auth/mfa/totp/confirm", { code }),
    );
    code = "";
    if (result) onDone(result);
  }
</script>

{#if step === "choose"}
  {#if error}<p class="alert alert-critical" role="alert">{error}</p>{/if}
  <div class="options">
    {#if passkeysWork}
      <button class="option" type="button" disabled={busy} onclick={choosePasskey}>
        <KeyRound size={22} aria-hidden="true" />
        <span>
          <span class="option-title">Passkey or security key</span>
          <span class="option-text small muted">
            Your device's fingerprint, face or PIN, or a key such as a YubiKey.
          </span>
        </span>
      </button>
    {/if}
    <button class="option" type="button" disabled={busy} onclick={chooseApp}>
      <Smartphone size={22} aria-hidden="true" />
      <span>
        <span class="option-title">Authenticator app</span>
        <span class="option-text small muted">
          A 6-digit code from an app such as Microsoft Authenticator or Google Authenticator.
        </span>
      </span>
    </button>
  </div>
{:else if enrolment && qr}
  <h2 class="step-title">Add Þing to your authenticator app</h2>
  <p class="muted">Scan the code with the app, then enter the 6-digit code it shows.</p>
  <svg
    class="qr"
    viewBox="0 0 {qr.size} {qr.size}"
    role="img"
    aria-label="QR code for your authenticator app"
    shape-rendering="crispEdges"
  >
    <rect width={qr.size} height={qr.size} fill="#FFFFFF" />
    <path d={qr.d} fill="#0F1B2D" />
  </svg>
  <div class="field">
    <span class="small muted">Can't scan it? Enter this key instead:</span>
    <span class="mono secret">{groupSecret(enrolment.secret)}</span>
  </div>
  <form class="stack" onsubmit={confirmApp}>
    {#if error}<p class="alert alert-critical" role="alert">{error}</p>{/if}
    <div class="field">
      <label for="{uid}-code">6-digit code</label>
      <CodeInput id="{uid}-code" bind:value={code} />
    </div>
    <button class="button button-primary button-block" type="submit" disabled={busy}>
      Confirm
    </button>
  </form>
  <button class="link-button" type="button" onclick={() => (step = "choose")}>
    Choose another way
  </button>
{/if}

<style>
  .options {
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
  }
  .option {
    display: flex;
    align-items: flex-start;
    gap: var(--space-3);
    width: 100%;
    padding: var(--space-4);
    border: 1px solid var(--border-strong);
    border-radius: var(--radius-md);
    background: transparent;
    color: var(--text);
    text-align: left;
    font: inherit;
    cursor: pointer;
  }
  .option:hover:not(:disabled) {
    background: var(--surface-subtle);
  }
  .option :global(svg) {
    flex: none; /* keep icons full size beside long descriptions */
  }
  .option-title {
    display: block;
    font: var(--type-label);
  }
  .option-text {
    display: block;
  }
  .step-title {
    font: var(--type-subheading);
  }
  .qr {
    width: 200px;
    height: 200px;
    align-self: center;
    border-radius: var(--radius-sm);
  }
  .secret {
    /* Wrap only between the groups of four, so each group stays readable. */
    overflow-wrap: normal;
  }
</style>
