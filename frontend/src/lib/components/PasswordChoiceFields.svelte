<script lang="ts">
  import type { PasswordChoice } from "#lib/admin.js";
  import PasswordRules from "./PasswordRules.svelte";

  let { choice = $bindable() }: { choice: PasswordChoice } = $props();
  const uid = $props.id();
</script>

<fieldset class="choice">
  <legend class="check-title">Password</legend>
  <label class="check">
    <input type="radio" name="{uid}-mode" value="random" bind:group={choice.mode} />
    <span>
      <span class="check-title">Let Þing make a one-time password</span>
      <span class="small muted">
        Random and shown once. It works for 7 days, and they choose their own when they sign in.
      </span>
    </span>
  </label>
  <label class="check">
    <input type="radio" name="{uid}-mode" value="chosen" bind:group={choice.mode} />
    <span>
      <span class="check-title">Choose the password</span>
      <span class="small muted">It has to pass the same rules as anyone's own password.</span>
    </span>
  </label>
  {#if choice.mode === "chosen"}
    <div class="chosen stack">
      <PasswordRules id="{uid}-rules" whose="their" />
      <div class="field">
        <label for="{uid}-password">New password</label>
        <input id="{uid}-password" class="input" type="password" autocomplete="new-password"
          aria-describedby="{uid}-rules" required bind:value={choice.password} />
      </div>
      <div class="field">
        <label for="{uid}-repeat">Repeat the password</label>
        <input id="{uid}-repeat" class="input" type="password" autocomplete="new-password"
          required bind:value={choice.repeat} />
      </div>
      <label class="check">
        <input type="checkbox" bind:checked={choice.mustChange} />
        <span>
          <span class="check-title">They change it when they first sign in</span>
          <span class="small muted">
            Recommended: then only they know their password. Untick only for a password they
            gave you themselves.
          </span>
        </span>
      </label>
    </div>
  {/if}
</fieldset>

<style>
  .choice {
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
    margin: 0;
    padding: 0;
    border: 0;
  }
  .choice legend {
    margin-bottom: var(--space-2);
  }
  .chosen {
    padding-left: var(--space-6);
  }
</style>
