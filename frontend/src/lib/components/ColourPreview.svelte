<script lang="ts">
  import { paletteFor } from "#lib/colours.js";

  // How the colours will look in light and in dark mode, before saving them.
  let { primary, accent }: { primary: string; accent: string } = $props();

  const modes = [
    { mode: "light" as const, name: "Light mode", bg: "#FFFFFF", text: "#0F1B2D", border: "#E5E5E5" },
    { mode: "dark" as const, name: "Dark mode", bg: "#13202F", text: "#E8ECF0", border: "#26384C" },
  ];

  // Colours set through the CSSOM: the page's CSP allows no inline style attributes.
  function colour(node: HTMLElement, vars: Record<string, string>) {
    const set = (next: Record<string, string>) => {
      for (const [name, value] of Object.entries(next)) node.style.setProperty(name, value);
    };
    set(vars);
    return { update: set };
  }
</script>

<div class="previews">
  {#each modes as look (look.mode)}
    {@const palette = paletteFor({ primary, accent }, look.mode)}
    <div
      class="preview"
      use:colour={{
        "--p-bg": look.bg, "--p-text": look.text, "--p-border": look.border,
        "--p-link": palette.link, "--p-button": palette.buttonBg,
        "--p-button-text": palette.buttonText, "--p-accent": palette.accent,
      }}
    >
      <p class="small">{look.name}</p>
      <span class="menu-item">Current page</span>
      <span class="sample-link">A link to a customer</span>
      <span class="sample-button">Save</span>
    </div>
  {/each}
</div>

<style>
  .previews {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: var(--space-3);
    max-width: 640px;
  }
  .preview {
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    gap: var(--space-3);
    padding: var(--space-4);
    border: 1px solid var(--p-border);
    border-radius: var(--radius-md);
    background: var(--p-bg);
    color: var(--p-text);
  }
  .menu-item {
    padding: 4px 10px;
    box-shadow: inset 3px 0 0 var(--p-accent);
    font: var(--type-label);
  }
  .sample-link {
    color: var(--p-link);
    text-decoration: underline;
  }
  .sample-button {
    padding: 6px 14px;
    border-radius: var(--radius-sm);
    background: var(--p-button);
    color: var(--p-button-text);
    font: var(--type-label);
  }
</style>
