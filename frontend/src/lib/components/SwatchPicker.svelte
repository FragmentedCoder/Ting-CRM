<script lang="ts">
  import { untrack } from "svelte";
  import { customSwatch, isCustom, type Swatch } from "#lib/colours.js";

  // Pick one colour from a short, contrast-checked list. With `siteName`, a first
  // option follows the site's colour (bound as ""). With `custom` (the site's
  // colours only), any colour can be picked too; Þing shows the shades it will
  // use so it stays readable.
  let {
    legend,
    hint,
    swatches,
    value = $bindable(""),
    siteName,
    custom,
    disabled = false,
  }: {
    legend: string;
    hint?: string;
    swatches: Swatch[];
    value?: string;
    siteName?: string;
    custom?: "primary" | "accent";
    disabled?: boolean;
  } = $props();

  const uid = $props.id();

  // The last colour picked by hand; starts from the choice when the picker opens.
  let picked = $state(
    untrack(() =>
      isCustom(value) ? value : (swatches.find((s) => s.key === value) ?? swatches[0]).light,
    ),
  );
  const own = $derived(custom ? customSwatch(picked, custom) : null);
  const customOn = $derived(isCustom(value));

  function pick(event: Event & { currentTarget: HTMLInputElement }) {
    picked = event.currentTarget.value.toUpperCase();
    value = picked;
  }

  // Colours set through the CSSOM: the page's CSP allows no inline style attributes.
  function paint(node: HTMLElement, swatch: Swatch) {
    const set = (next: Swatch) => {
      node.style.setProperty("--swatch-light", next.light);
      node.style.setProperty("--swatch-dark", next.dark);
    };
    set(swatch);
    return { update: set };
  }
</script>

<fieldset class="picker" {disabled} aria-describedby={hint ? `${uid}-hint` : undefined}>
  <legend class="check-title">{legend}</legend>
  {#if hint}<p class="small muted" id="{uid}-hint">{hint}</p>{/if}
  <div class="options">
    {#if siteName !== undefined}
      <label class="option">
        <input type="radio" name={uid} value="" bind:group={value} />
        <span class="dot site" aria-hidden="true"></span>
        <span>Site's ({siteName})</span>
      </label>
    {/if}
    {#each swatches as swatch (swatch.key)}
      <label class="option">
        <input type="radio" name={uid} value={swatch.key} bind:group={value} />
        <span class="dot" use:paint={swatch} aria-hidden="true"></span>
        <span>{swatch.name}</span>
      </label>
    {/each}
    {#if own}
      <label class="option">
        <input type="radio" name={uid} value={picked} bind:group={value} />
        <span class="dot" use:paint={own} aria-hidden="true"></span>
        <span>Custom</span>
      </label>
    {/if}
  </div>
  {#if own && customOn}
    <div class="custom">
      <label class="check-title" for="{uid}-colour">Your colour</label>
      <div class="custom-row">
        <input id="{uid}-colour" class="colour" type="color" value={picked.toLowerCase()}
          aria-describedby="{uid}-shades" oninput={pick} />
        <span class="mono">{picked}</span>
      </div>
      <p class="small muted" id="{uid}-shades">
        {#if own.light === picked && own.dark === picked}
          Used as it is, in light and dark mode.
        {:else}
          To stay readable, Þing uses
          <span class="mono">{own.light}</span> in light mode and
          <span class="mono">{own.dark}</span> in dark mode: the nearest shades of it that
          pass the contrast check.
        {/if}
      </p>
    </div>
  {/if}
</fieldset>

<style>
  .picker {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    margin: 0;
    padding: 0;
    border: 0;
  }
  .picker:disabled {
    opacity: 0.6;
  }
  .options {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2);
  }
  .option {
    position: relative;
    display: inline-flex;
    align-items: center;
    gap: var(--space-2);
    min-height: 40px;
    padding: 6px 12px 6px 8px;
    border: 1px solid var(--border);
    border-radius: var(--radius-pill);
    font: var(--type-body-sm);
    cursor: pointer;
  }
  /* Invisible but on top of the dot, so a click lands on the radio itself. */
  .option input {
    position: absolute;
    margin: 0;
    opacity: 0;
  }
  .option:has(input:checked) {
    border-color: var(--text);
    box-shadow: inset 0 0 0 1px var(--text);
  }
  .option:has(input:focus-visible) {
    outline: 2px solid var(--link);
    outline-offset: 2px;
  }
  .dot {
    width: 20px;
    height: 20px;
    border-radius: 50%;
    background: var(--swatch-light);
    box-shadow: inset 0 0 0 1px rgb(0 0 0 / 0.15);
  }
  .custom {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    max-width: 520px;
    padding: var(--space-3) var(--space-4);
    border-radius: var(--radius-md);
    background: var(--surface-subtle);
  }
  .custom-row {
    display: flex;
    align-items: center;
    gap: var(--space-3);
  }
  .colour {
    width: 56px;
    height: 36px;
    padding: 2px;
    border: 1px solid var(--border-strong);
    border-radius: var(--radius-sm);
    background: var(--surface);
    cursor: pointer;
  }
  .dot.site {
    background: none;
    box-shadow: none;
    border: 2px dashed var(--border-strong);
  }
  :global(:root[data-theme="dark"]) .dot:not(.site) {
    background: var(--swatch-dark);
  }
  @media (prefers-color-scheme: dark) {
    :global(:root:not([data-theme="light"])) .dot:not(.site) {
      background: var(--swatch-dark);
    }
  }
</style>
