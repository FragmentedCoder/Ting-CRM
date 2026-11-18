<script lang="ts">
  import Search from "@lucide/svelte/icons/search";
  import { onMount } from "svelte";
  import { ApiError } from "#lib/api.js";
  import { cvrLookupEnabled, lookUpCvr } from "#lib/cvr.js";

  // A company's own details, for adding a customer or a group's other company and for
  // changing them. How long its records are kept is for those who manage customers.
  // With the CVR lookup on, a CVR number fills in the name and address.
  let {
    values = $bindable(),
    retention = true,
    legal = "The company's legal name.",
  }: {
    values: { name: string; cvr: string; address: string; retention_months?: number };
    retention?: boolean;
    legal?: string;
  } = $props();

  const uid = $props.id();
  let canLookUp = $state(false);
  let looking = $state(false);
  let found = $state<{ tone: "ok" | "critical"; text: string } | null>(null);

  onMount(async () => {
    canLookUp = await cvrLookupEnabled();
  });

  async function lookUp() {
    const search = values.cvr.trim() || values.name.trim();
    if (!search) {
      found = { tone: "critical", text: "Type a CVR number or a name first." };
      return;
    }
    looking = true;
    found = null;
    try {
      const company = await lookUpCvr(search);
      values.cvr = company.cvr;
      values.name = company.name;
      values.address = company.address;
      found = { tone: "ok", text: `Filled in from the CVR register: ${company.name}.` };
    } catch (e) {
      found = { tone: "critical", text: e instanceof ApiError ? e.message : "The lookup didn't work. Type the details in." };
    } finally {
      looking = false;
    }
  }
</script>

<div class="field">
  <label for="{uid}-name">Name</label>
  <input id="{uid}-name" class="input" required maxlength="200" autocomplete="organization"
    bind:value={values.name} />
  <span class="hint">{legal}</span>
</div>
<div class="field">
  <label for="{uid}-cvr">CVR number (optional)</label>
  <div class="cvr-row">
    <input id="{uid}-cvr" class="input cvr" inputmode="numeric" maxlength="11"
      aria-describedby="{uid}-cvr-hint" bind:value={values.cvr} />
    {#if canLookUp}
      <button class="button button-secondary" type="button" disabled={looking} onclick={lookUp}>
        <Search size={16} aria-hidden="true" />{looking ? "Looking up…" : "Look up"}
      </button>
    {/if}
  </div>
  <span class="hint" id="{uid}-cvr-hint">
    8 digits. Leave it empty for a company outside Denmark or a private person.{#if canLookUp}
      Look up fills in the name and address from the CVR register (by the name, without a number).{/if}
  </span>
  {#if found}<p class="small {found.tone}" role="status">{found.text}</p>{/if}
</div>
<div class="field">
  <label for="{uid}-address">Address</label>
  <textarea id="{uid}-address" class="input" rows="3" maxlength="1000"
    bind:value={values.address}></textarea>
  <span class="hint">Kept encrypted with the customer's own key.</span>
</div>
{#if retention}
  <div class="field">
    <label for="{uid}-retention">Keep its records for</label>
    <input id="{uid}-retention" class="input number" type="number" min="1" max="120" required
      aria-describedby="{uid}-retention-hint" bind:value={values.retention_months} />
    <span class="hint" id="{uid}-retention-hint">
      Months after it stops being a customer. From 1 to 120.
    </span>
  </div>
{/if}

<style>
  .cvr,
  .number {
    max-width: 12rem;
  }
  .cvr-row {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2);
  }
  .ok {
    margin: 0;
    color: var(--ok-text);
  }
  .critical {
    margin: 0;
    color: var(--critical-text);
  }
</style>
