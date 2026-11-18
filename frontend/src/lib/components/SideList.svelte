<script lang="ts">
  import Search from "@lucide/svelte/icons/search";
  import type { Snippet } from "svelte";
  import type { SideGroup } from "#lib/sidelist.js";
  import Pill from "./Pill.svelte";

  // A list beside a page's details (Services, Systems, Agreements): a filter box,
  // groups with their counts, items with a second line for a note, and the chosen
  // item in the heather fill. On a phone it sits above the details.
  let {
    label,
    groups,
    selected,
    filterLabel = "Filter",
    footer,
  }: {
    label: string;
    groups: SideGroup[];
    selected: number | null;
    filterLabel?: string;
    footer?: Snippet;
  } = $props();

  const uid = $props.id();
  let query = $state("");

  const shown = $derived.by(() => {
    const needle = query.trim().toLowerCase();
    return groups
      .map((group) => ({
        ...group,
        items: needle
          ? group.items.filter((item) => `${item.label} ${item.note ?? ""} ${item.keywords ?? ""}`.toLowerCase().includes(needle))
          : group.items,
      }))
      .filter((group) => group.items.length || !needle);
  });
</script>

<nav class="side-list" aria-label={label}>
  <div class="filter">
    <label for="{uid}-filter" class="visually-hidden">{filterLabel}</label>
    <Search class="filter-icon" size={14} aria-hidden="true" />
    <input id="{uid}-filter" class="input" type="search" placeholder={filterLabel} bind:value={query} />
  </div>
  {#each shown as group (group.label)}
    {#if group.items.length}
      <div class="group">
        <Pill tone={group.tone ?? "neutral"} text="{group.label} · {group.items.length}" />
      </div>
      <ul>
        {#each group.items as item (item.id)}
          <li>
            <!-- eslint-disable-next-line svelte/no-navigation-without-resolve -- every item's href comes from resolve() -->
            <a class="item" class:on={item.id === selected} class:indent={item.indent} href={item.href}
              aria-current={item.id === selected ? "page" : undefined}>
              <span class="top">
                <span class="name" class:mono={item.mono}>{item.label}</span>
                {#each item.tags ?? [] as tag (tag.text)}<span class="tag {tag.tone}">{tag.text}</span>{/each}
              </span>
              {#if item.note}<span class="note {item.noteTone ?? 'muted'}">{item.note}</span>{/if}
            </a>
          </li>
        {/each}
      </ul>
    {/if}
  {/each}
  {#if query && !shown.some((group) => group.items.length)}
    <p class="small muted none">Nothing matches.</p>
  {/if}
  {#if footer}<div class="footer">{@render footer()}</div>{/if}
</nav>

<style>
  .side-list {
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
    padding: var(--space-3);
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    background: var(--surface);
  }
  .filter {
    position: relative;
    margin-bottom: var(--space-2);
  }
  .filter :global(.filter-icon) {
    position: absolute;
    top: 50%;
    left: 10px;
    color: var(--text-muted);
    transform: translateY(-50%);
  }
  .filter .input {
    min-height: 40px;
    padding-left: 30px;
  }
  .group {
    padding: var(--space-2) var(--space-1) var(--space-1);
  }
  ul {
    display: flex;
    flex-direction: column;
    gap: 2px;
    margin: 0;
    padding: 0;
    list-style: none;
  }
  .item {
    display: flex;
    flex-direction: column;
    justify-content: center;
    min-height: 40px;
    box-sizing: border-box;
    padding: var(--space-1) var(--space-3);
    border-radius: var(--radius-sm);
    color: var(--text);
    text-decoration: none;
  }
  .item:hover {
    background: var(--surface-subtle);
  }
  .item.indent {
    padding-left: calc(var(--space-3) + 16px);
  }
  .item.on {
    background: var(--accent-fill);
    color: var(--on-accent-fill);
  }
  .top {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-2);
  }
  .name {
    font: var(--type-body-sm);
    font-weight: 600;
  }
  .tag {
    padding: 0 6px;
    border-radius: var(--radius-pill);
    font-size: 11px;
    line-height: 16px;
  }
  .tag.info {
    background: var(--info-bg);
    color: var(--info-text);
  }
  .tag.neutral {
    background: var(--surface-subtle);
    color: var(--text);
  }
  .note {
    font-size: 12px;
    line-height: 16px;
  }
  .note.warning {
    color: var(--warning-text);
  }
  .note.muted {
    color: var(--text-muted);
  }
  .item.on .note {
    color: inherit;
  }
  .none {
    margin: 0;
    padding: var(--space-2);
  }
  .footer {
    margin-top: var(--space-2);
  }
</style>
