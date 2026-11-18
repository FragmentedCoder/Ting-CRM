<script lang="ts">
  import type { Snippet } from "svelte";
  import { mainRole, mayContactLine, type Contact } from "#lib/customers.js";
  import Pill from "./Pill.svelte";

  // A contact, the same everywhere (docs/architecture.md, shared parts): name and
  // role badge, their title, phone, email, and whether we may contact them. Inside a
  // site card it's white with a border. The heather dots along the right edge are
  // decoration; the text keeps clear of them.
  let {
    contact,
    inset = false,
    actions,
  }: { contact: Contact; inset?: boolean; actions?: Snippet } = $props();

  const role = $derived(mainRole(contact));
  const may = $derived(mayContactLine(contact));
</script>

<div class="person" class:inset>
  <div class="top">
    <span class="name">{contact.name}</span>
    {#if role}<Pill tone="info" text={role} />{/if}
    {#if actions}<span class="actions">{@render actions()}</span>{/if}
  </div>
  <span class="line muted">{contact.role || "No title"}</span>
  {#if contact.phone}
    <!-- eslint-disable-next-line svelte/no-navigation-without-resolve -- a phone number, not a page -->
    <a class="line mono" href="tel:{contact.phone.replace(/[^0-9+]/g, '')}">{contact.phone}</a>
  {:else}
    <span class="line muted">No phone</span>
  {/if}
  {#if contact.email}
    <!-- eslint-disable-next-line svelte/no-navigation-without-resolve -- an email address, not a page -->
    <a class="line" href="mailto:{contact.email}">{contact.email}</a>
  {:else}
    <span class="line muted">No email</span>
  {/if}
  <span class="line may {may.tone}">{may.text}</span>
</div>

<style>
  .person {
    position: relative;
    isolation: isolate;
    display: flex;
    flex-direction: column;
    gap: 2px;
    min-width: 0;
    overflow: hidden;
    padding: var(--space-3) 76px var(--space-3) var(--space-4);
    border-radius: var(--radius-md);
    background: var(--bg);
  }
  .person.inset {
    border: 1px solid var(--border);
    background: var(--surface);
  }
  /* The dots, fading out towards the text, and a soft ring in the corner. */
  .person::after {
    position: absolute;
    inset: 0 0 0 auto;
    z-index: -1;
    width: 64px;
    background-image:
      radial-gradient(circle, color-mix(in srgb, var(--accent) 55%, transparent) 1.4px, transparent 1.9px),
      radial-gradient(circle, color-mix(in srgb, var(--text) 10%, transparent) 1.2px, transparent 1.7px);
    background-position: 0 0, 6px 6px;
    background-size: 12px 12px;
    mask-image: linear-gradient(to left, #000, rgb(0 0 0 / 60%) 60%, transparent);
    content: "";
    pointer-events: none;
  }
  .person::before {
    position: absolute;
    right: -28px;
    bottom: -28px;
    z-index: -1;
    width: 96px;
    height: 96px;
    border: 10px solid color-mix(in srgb, var(--accent) 18%, transparent);
    border-radius: 50%;
    content: "";
    pointer-events: none;
  }
  .top {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-2);
  }
  .name {
    font-weight: 600;
  }
  .actions {
    margin-left: auto;
  }
  .line {
    overflow: hidden;
    font: var(--type-body-sm);
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .may {
    margin-top: 2px;
    font-weight: 500;
  }
  .ok {
    color: var(--ok-text);
  }
  .warning {
    color: var(--warning-text);
  }
</style>
