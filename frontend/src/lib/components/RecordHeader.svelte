<script lang="ts">
  import type { Component, Snippet } from "svelte";

  // The top of a record's pages (a customer's): what it is, its name with its
  // status badges across from it, and a line about it underneath. A logo, when
  // there is one, takes the icon's place.
  let {
    kind,
    title,
    icon: Icon,
    image = null,
    badges,
    children,
  }: {
    kind: string;
    title: string;
    icon: Component<{ size?: number }>;
    image?: string | null;
    badges?: Snippet;
    children?: Snippet;
  } = $props();
</script>

<header class="record">
  {#if image}
    <img class="logo" src={image} alt="" height="48" />
  {:else}
    <span class="tile" aria-hidden="true"><Icon size={24} /></span>
  {/if}
  <div class="text">
    <p class="eyebrow small muted">{kind}</p>
    <div class="name">
      <h1 class="title">{title}</h1>
      {#if badges}<div class="badges">{@render badges()}</div>{/if}
    </div>
    {@render children?.()}
  </div>
</header>

<style>
  .record {
    display: flex;
    align-items: center;
    gap: var(--space-4);
    min-width: 0;
  }
  .text {
    flex: 1 1 auto;
    min-width: 0;
  }
  .eyebrow {
    font: var(--type-overline);
    letter-spacing: var(--type-overline-tracking);
    text-transform: uppercase;
  }
  /* The name, and the badges at the far end of its line; under a name too long
     to share the line, they keep to the right. */
  .name {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-2) var(--space-4);
  }
  .title {
    min-width: 0;
    overflow-wrap: anywhere;
  }
  .badges {
    display: flex;
    flex-wrap: wrap;
    justify-content: flex-end;
    gap: var(--space-2);
    margin-left: auto;
  }
  .logo {
    width: auto;
    max-width: 160px;
    height: 48px;
    object-fit: contain;
  }
  .tile {
    display: grid;
    flex: none;
    place-items: center;
    width: 48px;
    height: 48px;
    border-radius: var(--radius-md);
    background: var(--surface-subtle);
    color: var(--text-muted);
  }
</style>
