<script lang="ts">
  import { onMount } from "svelte";
  import { api } from "#lib/api.js";

  // What a new password must meet, from the current security settings.
  // "their" when an administrator sets someone else's password.
  let { id, whose = "your" }: { id?: string; whose?: "your" | "their" } = $props();

  let rules = $state<{ min_length: number; breach_check: boolean } | null>(null);

  onMount(async () => {
    try {
      rules = await api("GET", "/auth/password-rules");
    } catch {
      rules = null; // the form still works; the server checks every rule anyway
    }
  });
</script>

{#if rules}
  <div class="rules small" {id}>
    <p>A good password here:</p>
    <ul>
      <li>has at least {rules.min_length} characters. Spaces are fine, so a few unrelated words make a passphrase that's easy to remember and hard to guess;</li>
      <li>doesn't contain {whose} username or the product name (“Þing”, or “ting” or “thing” as a word);</li>
      {#if rules.breach_check}
        <li>
          hasn't appeared in a known data breach. Þing checks with Have I Been Pwned, and only
          the first 5 characters of a scrambled copy of the password leave the server.
        </li>
      {/if}
    </ul>
    <p class="muted">There are no rules about capital letters, digits or symbols: length protects better.</p>
  </div>
{/if}

<style>
  .rules {
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
    max-width: 640px;
    padding: var(--space-3) var(--space-4);
    border-radius: var(--radius-md);
    background: var(--surface-subtle);
  }
  ul {
    margin: 0;
    padding-left: 1.2em;
  }
</style>
