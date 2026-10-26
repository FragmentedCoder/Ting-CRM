<script lang="ts">
  import { goto } from "$app/navigation";
  import { resolve } from "$app/paths";
  import Building from "@lucide/svelte/icons/building";
  import ChevronsUpDown from "@lucide/svelte/icons/chevrons-up-down";
  import Search from "@lucide/svelte/icons/search";
  import { onDestroy, tick } from "svelte";
  import { formatCvr } from "#lib/customers.js";
  import { openCustomer, workspace } from "#lib/workspace.svelte.js";

  // The customer switcher at the top of the side menu: a button naming the open
  // customer, and a searchable list in a popover (above everything, not clipped).
  const uid = $props.id();
  let button: HTMLButtonElement;
  let panel: HTMLDivElement;
  let search = $state<HTMLInputElement>();
  let query = $state("");
  let expanded = $state(false);

  const current = $derived(openCustomer());
  const matches = $derived(
    (workspace.customers ?? []).filter((c) => {
      const needle = query.trim().toLowerCase().replace(/\s/g, "");
      return !needle || `${c.name}${c.cvr ?? ""}`.toLowerCase().replace(/\s/g, "").includes(needle);
    }),
  );

  function place() {
    const box = button.getBoundingClientRect();
    panel.style.top = `${box.bottom + 4}px`;
    panel.style.left = `${box.left}px`;
    panel.style.width = `${box.width}px`;
  }

  // Placed under its button before it shows, so it never appears anywhere else.
  function opening(event: ToggleEvent) {
    if (event.newState === "open") place();
  }

  // While open it follows its button when the menu or page scrolls or resizes.
  function follow(on: boolean) {
    const method = on ? "addEventListener" : "removeEventListener";
    window[method]("scroll", place, true);
    window[method]("resize", place);
  }

  async function toggled(event: ToggleEvent) {
    expanded = event.newState === "open";
    follow(expanded);
    if (!expanded) return;
    query = "";
    await tick();
    search?.focus();
  }

  onDestroy(() => follow(false));

  async function pick(id: number) {
    panel.hidePopover();
    await goto(resolve("/(app)/customers/[id]", { id: String(id) }));
  }

  // Enter opens the only match, so a few letters and Enter is enough.
  function keys(event: KeyboardEvent) {
    if (event.key === "Enter" && matches.length === 1) {
      event.preventDefault();
      void pick(matches[0].id);
    }
  }
</script>

<button
  bind:this={button}
  class="picker"
  type="button"
  aria-haspopup="dialog"
  aria-expanded={expanded}
  aria-controls="{uid}-panel"
  popovertarget="{uid}-panel"
>
  <Building size={18} aria-hidden="true" />
  <span class="label">
    <span class="small muted">Customer</span>
    <span class="name">{current?.name ?? "Choose a customer"}</span>
  </span>
  <ChevronsUpDown size={16} aria-hidden="true" />
</button>

<div bind:this={panel} id="{uid}-panel" class="panel" popover="auto" role="dialog"
  aria-label="Choose a customer" onbeforetoggle={opening} ontoggle={toggled}>
  <div class="search">
    <Search size={16} aria-hidden="true" />
    <input bind:this={search} type="search" placeholder="Search by name or CVR"
      aria-label="Search customers" bind:value={query} onkeydown={keys} />
  </div>
  {#if matches.length}
    <ul class="list">
      {#each matches as customer (customer.id)}
        <li>
          <button type="button" class="option" aria-current={customer.id === current?.id ? "true" : undefined}
            onclick={() => pick(customer.id)}>
            <span class="name">{customer.name}</span>
            {#if customer.visibility === "full"}
              {#if customer.cvr}<span class="small muted mono">{formatCvr(customer.cvr)}</span>{/if}
            {:else}
              <span class="small muted">Overview</span>
            {/if}
          </button>
        </li>
      {/each}
    </ul>
  {:else}
    <p class="small muted empty">
      {workspace.customers?.length ? "No customer matches that." : "No customers yet."}
    </p>
  {/if}
</div>

<style>
  .picker {
    display: flex;
    align-items: center;
    gap: var(--space-3);
    width: 100%;
    padding: 8px 10px;
    border: 1px solid var(--border-strong);
    border-radius: var(--radius-md);
    background: var(--surface);
    color: var(--text);
    text-align: left;
    cursor: pointer;
  }
  .picker:hover {
    background: var(--surface-subtle);
  }
  .label {
    display: flex;
    flex: 1;
    flex-direction: column;
    min-width: 0;
  }
  .name {
    overflow: hidden;
    font: var(--type-label);
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .panel {
    position: fixed;
    inset: auto;
    max-height: min(420px, 70vh);
    margin: 0;
    padding: var(--space-2);
    overflow: auto;
    border: 1px solid var(--border);
    border-radius: var(--radius-md);
    background: var(--surface);
    color: var(--text);
    box-shadow: 0 8px 24px rgb(11 20 32 / 0.18);
  }
  .search {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    padding: 6px 10px;
    border: 1px solid var(--border-strong);
    border-radius: var(--radius-sm);
    color: var(--text-muted);
  }
  .search input {
    flex: 1;
    min-width: 0;
    border: 0;
    background: none;
    color: var(--text);
    font: var(--type-body-sm);
    outline: none;
  }
  .search:focus-within {
    outline: 2px solid var(--link);
    outline-offset: 1px;
  }
  .list {
    margin: var(--space-2) 0 0;
    padding: 0;
    list-style: none;
  }
  .option {
    display: flex;
    flex-direction: column;
    width: 100%;
    padding: 8px 10px;
    border: 0;
    border-radius: var(--radius-sm);
    background: none;
    color: var(--text);
    text-align: left;
    cursor: pointer;
  }
  .option:hover,
  .option:focus-visible,
  .option[aria-current="true"] {
    background: var(--surface-subtle);
    outline: none;
  }
  .option[aria-current="true"] {
    box-shadow: inset 3px 0 0 var(--accent);
  }
  .empty {
    padding: var(--space-3) var(--space-2) var(--space-1);
  }
</style>
