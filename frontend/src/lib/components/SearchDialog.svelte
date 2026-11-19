<script lang="ts">
  import { goto } from "$app/navigation";
  import { resolve } from "$app/paths";
  import Search from "@lucide/svelte/icons/search";
  import { tick } from "svelte";
  import { api, ApiError, sessionGone } from "#lib/api.js";
  import { statusPill } from "#lib/customers.js";
  import { HIT_KINDS, SEARCH_FROM, hitPath, type Found, type Hit } from "#lib/search.js";
  import Pill from "./Pill.svelte";

  // Global search, from every screen (Ctrl+K or "/"): type a company name, a CVR
  // number, a contact, a phone number, an email domain, a case number or a system,
  // and open the customer on the page that shows it. Arrow keys move through the
  // hits, Enter opens one.
  let { open = $bindable(false) }: { open?: boolean } = $props();

  const uid = $props.id();
  let dialog: HTMLDialogElement;
  let input = $state<HTMLInputElement>();
  let query = $state("");
  let found = $state<Found | null>(null);
  let error = $state<string | null>(null);
  let active = $state(0);
  let timer: ReturnType<typeof setTimeout> | undefined;
  let asked = 0;

  const hits = $derived(found?.hits ?? []);
  const typed = $derived(query.trim());

  $effect(() => {
    if (open && !dialog.open) {
      query = "";
      found = null;
      error = null;
      dialog.showModal();
      void tick().then(() => input?.focus());
    } else if (!open && dialog.open) {
      dialog.close();
    }
  });

  // Asks once typing pauses; an answer to an earlier question is dropped.
  function changed() {
    clearTimeout(timer);
    const wanted = query.trim();
    if (wanted.length < SEARCH_FROM) {
      asked++;
      found = null;
      error = null;
      return;
    }
    timer = setTimeout(async () => {
      const mine = ++asked;
      try {
        const answer = await api<Found>("GET", `/search?q=${encodeURIComponent(wanted)}`);
        if (mine !== asked) return;
        [found, error, active] = [answer, null, 0];
      } catch (e) {
        if (mine === asked && !sessionGone(e)) error = e instanceof ApiError ? e.message : "Search isn't available.";
      }
    }, 150);
  }

  async function go(hit: Hit) {
    open = false;
    const { page, query: where } = hitPath(hit);
    const base = resolve("/(app)/customers/[id]", { id: String(hit.customer_id) });
    // eslint-disable-next-line svelte/no-navigation-without-resolve -- built on resolve(), plus the page and what to open on it
    await goto(`${base}${page}${where}`);
  }

  function keys(event: KeyboardEvent) {
    if (!hits.length) return;
    const moves: Record<string, number> = {
      ArrowDown: (active + 1) % hits.length,
      ArrowUp: (active - 1 + hits.length) % hits.length,
      Home: 0,
      End: hits.length - 1,
    };
    if (event.key in moves && (event.key.startsWith("Arrow") || event.ctrlKey)) {
      event.preventDefault();
      active = moves[event.key];
      document.getElementById(`${uid}-hit-${active}`)?.scrollIntoView({ block: "nearest" });
    } else if (event.key === "Enter") {
      event.preventDefault();
      void go(hits[active]);
    }
  }
</script>

<dialog bind:this={dialog} aria-label="Search" onclose={() => (open = false)}>
  <!-- Only while it's open: closed, it leaves nothing on the page to find or tab to. -->
  {#if open}
    <div class="box">
      <div class="ask">
        <Search size={18} aria-hidden="true" />
        <input bind:this={input} type="search" role="combobox" aria-label="Search customers, contacts, case numbers and systems"
          aria-expanded={hits.length > 0} aria-controls="{uid}-hits" aria-autocomplete="list"
          aria-activedescendant={hits.length ? `${uid}-hit-${active}` : undefined}
          placeholder="A company, CVR number, contact, phone number, case number or system"
          autocomplete="off" spellcheck="false" maxlength="100" bind:value={query} oninput={changed} onkeydown={keys} />
        <kbd class="small">Esc</kbd>
      </div>
      {#if error}<p class="alert alert-critical" role="alert">{error}</p>{/if}
      <ul class="hits" id="{uid}-hits" role="listbox" aria-label="Search results">
        {#each hits as hit, index (`${hit.kind}-${hit.customer_id}-${hit.record_id}-${hit.title}`)}
          <!-- svelte-ignore a11y_click_events_have_key_events -->
          <li id="{uid}-hit-{index}" class="hit" class:active={index === active} role="option"
            aria-selected={index === active} onclick={() => go(hit)} onpointermove={() => (active = index)}>
            <span class="top">
              <Pill tone="info" text={HIT_KINDS[hit.kind]} />
              <span class="strong">{hit.title}</span>
              {#if hit.status && hit.status !== "active"}<Pill {...statusPill(hit.status)} />{/if}
            </span>
            <span class="small muted">{[hit.kind === "customer" ? null : hit.customer, hit.detail].filter(Boolean).join(" · ")}</span>
          </li>
        {/each}
      </ul>
      <p class="small muted note" aria-live="polite">
        {#if typed.length < SEARCH_FROM}
          Type a company name, a CVR number, a contact's name, a phone number, an email domain, a case number or a system.
        {:else if found && !hits.length}
          Nothing found for “{typed}”.
        {:else if found?.more}
          More match than are shown. Type more to narrow it down.
        {:else if found}
          {hits.length === 1 ? "1 found." : `${hits.length} found.`} Arrow keys to move, Enter to open.
        {/if}
      </p>
    </div>
  {/if}
</dialog>

<style>
  dialog {
    width: min(640px, calc(100vw - 2 * var(--space-4)));
    max-height: min(560px, calc(100vh - 2 * var(--space-8)));
    margin-top: var(--space-16);
    padding: 0;
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    background: var(--surface);
    color: var(--text);
  }
  dialog::backdrop {
    background: rgb(11 20 32 / 0.55);
  }
  .box {
    display: flex;
    flex-direction: column;
    max-height: inherit;
  }
  .ask {
    display: flex;
    align-items: center;
    gap: var(--space-3);
    padding: var(--space-3) var(--space-4);
    border-bottom: 1px solid var(--border);
    color: var(--text-muted);
  }
  .ask input {
    flex: 1;
    min-width: 0;
    padding: var(--space-2) 0;
    border: 0;
    outline: 0;
    background: transparent;
    color: var(--text);
    font: var(--type-body);
  }
  kbd {
    padding: 1px 6px;
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    font: var(--type-code);
  }
  .hits {
    flex: 1;
    min-height: 0;
    margin: 0;
    padding: var(--space-2);
    overflow-y: auto;
    list-style: none;
  }
  .hits:empty {
    display: none;
  }
  .hit {
    display: flex;
    flex-direction: column;
    gap: 2px;
    padding: var(--space-2) var(--space-3);
    border-radius: var(--radius-sm);
    cursor: pointer;
  }
  .hit.active {
    background: var(--surface-subtle);
  }
  .top {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-2);
  }
  .strong {
    font-weight: 600;
  }
  .note {
    margin: 0;
    padding: var(--space-3) var(--space-4);
    border-top: 1px solid var(--border);
  }
  .alert {
    margin: var(--space-3) var(--space-4) 0;
  }
</style>
