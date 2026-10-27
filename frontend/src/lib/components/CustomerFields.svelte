<script lang="ts">
  // A customer's own details, for adding one and for changing them. How long its
  // records are kept is for Administrators only.
  let {
    values = $bindable(),
    retention = true,
  }: {
    values: { name: string; cvr: string; address: string; retention_months: number };
    retention?: boolean;
  } = $props();

  const uid = $props.id();
</script>

<div class="field">
  <label for="{uid}-name">Name</label>
  <input id="{uid}-name" class="input" required maxlength="200" autocomplete="organization"
    bind:value={values.name} />
  <span class="hint">The company's legal name.</span>
</div>
<div class="field">
  <label for="{uid}-cvr">CVR number (optional)</label>
  <input id="{uid}-cvr" class="input cvr" inputmode="numeric" maxlength="11"
    aria-describedby="{uid}-cvr-hint" bind:value={values.cvr} />
  <span class="hint" id="{uid}-cvr-hint">8 digits. Leave it empty for a customer outside Denmark.</span>
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
</style>
