<script lang="ts">
  import { page } from "$app/state";
  import type { Snippet } from "svelte";
  import { can, session } from "#lib/session.svelte.js";

  // The admin panel's pages. Their sections are in the side menu, under Admin.
  // Managers have one of them: General, for how far ahead Þing looks.
  let { children }: { children: Snippet } = $props();
  // The Managers' part: General, and Admin itself, which leads there.
  const MANAGERS = /^\/admin(\/general)?\/?$/;

  // The live session, so rights that change (a role, the allowlist) show at once.
  const allowed = $derived(
    can(session.current, "administer") || can(session.current, "read_audit_log")
      || (can(session.current, "manage_customers") && MANAGERS.test(page.url.pathname)),
  );
</script>

{#if allowed}
  <main class="page-content">{@render children()}</main>
{:else}
  <main class="page-content">
    <h1 class="title">Admin</h1>
    <p class="alert alert-warning">You don't have access to the admin panel.</p>
  </main>
{/if}
