<script lang="ts">
  import { api, ApiError } from "#lib/api.js";
  import { session, useSession, type SecondFactorResult } from "#lib/session.svelte.js";
  import { finishStepUp, stepUp } from "#lib/stepUp.svelte.js";
  import Dialog from "./Dialog.svelte";
  import VerifySecondFactor from "./VerifySecondFactor.svelte";

  let password = $state("");
  let error = $state<string | null>(null);
  let busy = $state(false);
  const uid = $props.id();

  const info = $derived(session.current);
  const hasFactors = $derived(
    info?.methods.some((method) => method === "totp" || method === "webauthn") ?? false,
  );

  // Closing the dialog any way (Escape, Cancel) means "don't".
  $effect(() => {
    if (!stepUp.open) {
      password = "";
      error = null;
    }
  });

  function verified(result: SecondFactorResult) {
    useSession(result.session);
    finishStepUp(true);
  }

  async function confirmPassword(event: SubmitEvent) {
    event.preventDefault();
    busy = true;
    error = null;
    try {
      await api("POST", "/auth/confirm-password", { password });
      finishStepUp(true);
    } catch (e) {
      error = e instanceof ApiError ? e.message : "Something went wrong. Try again.";
    } finally {
      password = "";
      busy = false;
    }
  }
</script>

<Dialog
  bind:open={() => stepUp.open, (open) => { if (!open) finishStepUp(false); }}
  title="Confirm it's you"
>
  <p class="muted">
    This change weakens security or can sign people out, so Þing checks it's really you.
  </p>
  {#if stepUp.open && info}
    {#if hasFactors}
      <VerifySecondFactor {info} onDone={verified} />
    {:else}
      <form class="stack" onsubmit={confirmPassword}>
        {#if error}<p class="alert alert-critical" role="alert">{error}</p>{/if}
        <div class="field">
          <label for="{uid}-password">Your password</label>
          <input id="{uid}-password" class="input" type="password"
            autocomplete="current-password" required bind:value={password} />
        </div>
        <button class="button button-primary" type="submit" disabled={busy}>Confirm</button>
      </form>
    {/if}
  {/if}
  {#snippet actions()}
    <button class="button button-secondary" type="button" onclick={() => finishStepUp(false)}>
      Cancel
    </button>
  {/snippet}
</Dialog>
