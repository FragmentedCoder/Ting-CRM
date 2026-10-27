<script lang="ts">
  import { branding } from "#lib/branding.svelte.js";
  import Mark from "./Mark.svelte";

  // The company's logo and site name when an Administrator set them, else Þing's;
  // under the name the tag line when asked for.
  let {
    size = 32,
    tagline = false,
  }: { size?: number; tagline?: boolean } = $props();

  const look = $derived(branding.current);
</script>

<span class="brand">
  {#if look.logo_url}
    <img class="logo" src={look.logo_url} alt="" height={size} />
  {:else}
    <Mark {size} />
  {/if}
  <span class="names">
    <span class="wordmark">{look.site_name}</span>
    {#if tagline && look.tagline}
      <span class="tagline small muted" title={look.tagline}>{look.tagline}</span>
    {/if}
  </span>
</span>

<style>
  .brand {
    display: flex;
    align-items: center;
    gap: var(--space-3);
    min-width: 0;
  }
  .logo {
    flex: none;
    width: auto;
    max-width: 160px;
    object-fit: contain;
  }
  .names {
    display: flex;
    flex-direction: column;
    min-width: 0;
  }
  .wordmark,
  .tagline {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .wordmark {
    font: var(--type-subheading);
  }
</style>
