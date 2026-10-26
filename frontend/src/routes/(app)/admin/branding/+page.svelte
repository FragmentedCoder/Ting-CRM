<script lang="ts">
  import ImageIcon from "@lucide/svelte/icons/image";
  import { onMount } from "svelte";
  import { api, ApiError } from "#lib/api.js";
  import { branding, loadBranding, pageTitle, useBranding, type Branding } from "#lib/branding.svelte.js";
  import { ACCENT, PRIMARY } from "#lib/colours.js";
  import Brand from "#lib/components/Brand.svelte";
  import ColourPreview from "#lib/components/ColourPreview.svelte";
  import Switch from "#lib/components/Switch.svelte";
  import SwatchPicker from "#lib/components/SwatchPicker.svelte";
  import { toast } from "#lib/toast.svelte.js";

  let form = $state({
    site_name: "",
    tagline: "",
    company_name: "",
    primary_colour: "fjord",
    accent_colour: "rav",
    enforce_colours: false,
  });
  let loaded = $state(false);
  let error = $state<string | null>(null);
  let busy = $state(false);
  let fileInput = $state<HTMLInputElement>();

  onMount(async () => {
    await loadBranding();
    const current = branding.current;
    form = {
      site_name: current.site_name,
      tagline: current.tagline,
      company_name: current.company_name ?? "",
      primary_colour: current.primary_colour,
      accent_colour: current.accent_colour,
      enforce_colours: current.enforce_colours,
    };
    loaded = true;
  });

  async function run(action: () => Promise<Branding>, done: string) {
    busy = true;
    error = null;
    try {
      useBranding(await action());
      toast(done, "ok", { key: "saved" });
    } catch (e) {
      error = e instanceof ApiError ? e.message : "Something went wrong. Try again.";
    } finally {
      busy = false;
    }
  }

  function save(event: SubmitEvent, done = "Branding saved.") {
    event.preventDefault();
    run(() => api<Branding>("PUT", "/admin/branding", form), done);
  }

  function upload() {
    const file = fileInput?.files?.[0];
    if (fileInput) fileInput.value = "";
    if (!file) return;
    if (file.size > 2 * 1024 * 1024) {
      error = "The image is larger than 2 MB.";
      return;
    }
    run(() => api<Branding>("PUT", "/admin/branding/logo", file), "Logo uploaded.");
  }
</script>

<svelte:head><title>{pageTitle("Branding · Admin")}</title></svelte:head>

<div class="page-header">
  <div>
    <h1 class="title">Branding</h1>
    <p class="small muted">The name, tag line and logo people see when they sign in and work.</p>
  </div>
</div>

{#if error}<p class="alert alert-critical" role="alert">{error}</p>{/if}

{#if loaded}
  <section class="section" aria-labelledby="preview-title">
    <h2 class="section-title" id="preview-title">Preview</h2>
    <p class="small muted">How the side menu and the sign-in page show your site, as saved.</p>
    <div class="preview">
      <Brand size={40} tagline />
    </div>
  </section>

  <section class="section" aria-labelledby="names-title">
    <h2 class="section-title" id="names-title">Names</h2>
    <p class="small muted">What people see when they sign in and work, and the name on reports.</p>
    <form class="stack form-narrow" onsubmit={save}>
      <div class="field">
        <label for="site-name">Site name</label>
        <input id="site-name" class="input" required maxlength="60" bind:value={form.site_name} />
        <span class="hint">Shown in the side menu, on the sign-in page and in browser tabs.</span>
      </div>
      <div class="field">
        <label for="tagline">Tag line</label>
        <input id="tagline" class="input" maxlength="120" bind:value={form.tagline} />
        <span class="hint">Shown beside the name on the sign-in page. Leave it empty for none.</span>
      </div>
      <div class="field">
        <label for="company-name">Company name</label>
        <input id="company-name" class="input" required maxlength="200" autocomplete="organization"
          bind:value={form.company_name} />
        <span class="hint">Your company's legal name, as it appears on reports.</span>
      </div>
      <div><button class="button button-primary" type="submit" disabled={busy}>Save</button></div>
    </form>
  </section>

  <section class="section" aria-labelledby="colours-title">
    <h2 class="section-title" id="colours-title">Colours</h2>
    <p class="small muted">
      The site's colours. Pick from the list or choose any colour with Custom. People can pick
      their own in Your account, unless you set these for everyone. Every colour is checked to
      stay readable in light and dark mode; a custom one is shaded only as far as that needs.
    </p>
    <form class="stack" onsubmit={(event) => save(event, "Colours saved.")}>
      <SwatchPicker legend="Primary colour" hint="Links, buttons, switches and focus outlines."
        swatches={PRIMARY} custom="primary" bind:value={form.primary_colour} />
      <SwatchPicker legend="Accent colour" hint="Marks where you are in the menus, and commands to copy."
        swatches={ACCENT} custom="accent" bind:value={form.accent_colour} />
      <ColourPreview primary={form.primary_colour} accent={form.accent_colour} />
      <Switch title="Use these colours for everyone" bind:checked={form.enforce_colours}>
        People's own colour choices are kept, but don't apply while this is on.
      </Switch>
      <div><button class="button button-primary" type="submit" disabled={busy}>Save colours</button></div>
    </form>
  </section>

  <section class="section" aria-labelledby="logo-title">
    <h2 class="section-title" id="logo-title">Logo</h2>
    <p class="small muted">
      A PNG, JPEG, WebP or GIF up to 2 MB. Þing scales it to fit 512 × 512 pixels and removes
      any hidden data. A wide logo on a transparent background works best.
    </p>
    <input bind:this={fileInput} id="logo-file" class="visually-hidden" type="file"
      accept="image/png,image/jpeg,image/webp,image/gif" onchange={upload} />
    <div class="button-row">
      <button class="button button-secondary" type="button" disabled={busy}
        onclick={() => fileInput?.click()}>
        <ImageIcon size={16} aria-hidden="true" />
        {branding.current.logo_url ? "Replace logo" : "Upload a logo"}
      </button>
      {#if branding.current.logo_url}
        <button class="button button-secondary" type="button" disabled={busy}
          onclick={() => run(() => api<Branding>("DELETE", "/admin/branding/logo"), "Logo removed.")}>
          Use Þing's mark instead
        </button>
      {/if}
    </div>
  </section>
{/if}

<style>
  .preview {
    display: flex;
    padding: var(--space-6);
    border: 1px dashed var(--border-strong);
    border-radius: var(--radius-md);
    background: var(--surface);
  }
</style>
