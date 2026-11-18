<script lang="ts" generics="T extends string">
  // Filter chips: one choice from a few, each with how many it shows. The chosen
  // one is ink on snow (docs/brand), and says so to screen readers.
  let {
    label,
    options,
    value = $bindable(),
  }: {
    label: string;
    options: { value: T; label: string; count?: number }[];
    value: T;
  } = $props();
</script>

<div class="chips" role="group" aria-label={label}>
  {#each options as option (option.value)}
    <button class="chip" class:on={value === option.value} type="button"
      aria-pressed={value === option.value} onclick={() => (value = option.value)}>
      {option.label}{#if option.count !== undefined}<span class="count"> · {option.count}</span>{/if}
    </button>
  {/each}
</div>

<style>
  .chips {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2);
  }
  .chip {
    min-height: 36px;
    padding: 0 var(--space-4);
    border: 1px solid var(--border-strong);
    border-radius: var(--radius-pill);
    background: var(--surface);
    color: var(--text);
    font: var(--type-label);
    cursor: pointer;
  }
  .chip:hover {
    background: var(--surface-subtle);
  }
  .chip.on {
    border-color: var(--button-bg);
    background: var(--button-bg);
    color: var(--button-text);
  }
</style>
