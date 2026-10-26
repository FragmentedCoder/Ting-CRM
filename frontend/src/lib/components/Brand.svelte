<script lang="ts">
  import { branding } from "#lib/branding.svelte.js";
  import Mark from "./Mark.svelte";

  // The company's logo and site name when an Administrator set them, else Þing's;
  // under the name the tag line, and the version when given.
  let {
    size = 32,
    tagline = false,
    version = null,
  }: { size?: number; tagline?: boolean; version?: string | null } = $props();

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
    {#if (tagline && look.tagline) || version}
      <span class="under small muted">
        {#if tagline && look.tagline}<span class="tagline" title={look.tagline}>{look.tagline}</span>{/if}
        {#if version}<span class="version" title="Þing {version}">{version}</span>{/if}
      </span>
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
  /* The tag line, and beside it which Þing this is; the tag line gives way. */
  .under {
    display: flex;
    align-items: baseline;
    gap: var(--space-2);
    min-width: 0;
  }
  .version {
    flex: none;
    padding: 0 var(--space-2);
    border: 1px solid var(--border);
    border-radius: 999px;
    white-space: nowrap;
  }
</style>
