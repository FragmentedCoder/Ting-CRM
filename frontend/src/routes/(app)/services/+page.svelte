<script lang="ts">
  import Pencil from "@lucide/svelte/icons/pencil";
  import Plus from "@lucide/svelte/icons/plus";
  import Trash from "@lucide/svelte/icons/trash-2";
  import X from "@lucide/svelte/icons/x";
  import { onMount } from "svelte";
  import { api, ApiError, sessionGone } from "#lib/api.js";
  import { pageTitle } from "#lib/branding.svelte.js";
  import Dialog from "#lib/components/Dialog.svelte";
  import Pill from "#lib/components/Pill.svelte";
  import RowMenu from "#lib/components/RowMenu.svelte";
  import { DETAIL_KINDS, type DetailField, type StandardService } from "#lib/services.js";
  import { can, session } from "#lib/session.svelte.js";
  import { toast } from "#lib/toast.svelte.js";

  // The catalog every customer's services are copied from: each standard service with
  // the details worth recording. Managers keep it; a change never rewrites a
  // customer's copy, but details added here show up on the copies to fill in.
  const mayKeep = $derived(can(session.current, "manage_service_catalog"));
  let services = $state<StandardService[] | null>(null);
  let error = $state<string | null>(null);
  let busy = $state(false);
  let open = $state(false);
  let draft = $state<{ id: number | null; name: string; description: string; details: (DetailField & { choiceText: string })[] }>(
    { id: null, name: "", description: "", details: [] });
  let removing = $state<StandardService | null>(null);
  let removeOpen = $state(false);

  onMount(async () => {
    try {
      services = await api<StandardService[]>("GET", "/services");
    } catch (e) {
      if (!sessionGone(e)) error = e instanceof ApiError ? e.message : "The catalog could not be loaded.";
    }
  });

  function edit(found?: StandardService) {
    draft = found
      ? { id: found.id, name: found.name, description: found.description,
          details: found.details.map((d) => ({ ...d, choiceText: d.choices.join(", ") })) }
      : { id: null, name: "", description: "", details: [] };
    error = null;
    open = true;
  }

  function addDetail() {
    draft.details.push({ key: "", label: "", kind: "text", choices: [], help: "", choiceText: "" });
  }

  async function save(event: SubmitEvent) {
    event.preventDefault();
    busy = true;
    error = null;
    const body = {
      name: draft.name, description: draft.description,
      details: draft.details.map(({ choiceText, ...d }) => ({ ...d, choices: d.kind === "choice" ? choiceText.split(",") : [] })),
    };
    try {
      const saved = await api<StandardService>(draft.id === null ? "POST" : "PUT",
        draft.id === null ? "/services" : `/services/${draft.id}`, body);
      services = draft.id === null ? [...(services ?? []), saved] : (services ?? []).map((s) => (s.id === saved.id ? saved : s));
      open = false;
      toast(`${saved.name} is saved.`, "ok", { key: "saved" });
    } catch (e) {
      if (!sessionGone(e)) error = e instanceof ApiError ? e.message : "Something went wrong. Try again.";
    } finally {
      busy = false;
    }
  }

  async function remove() {
    const gone = removing;
    removeOpen = false;
    if (!gone) return;
    try {
      await api("DELETE", `/services/${gone.id}`);
      services = (services ?? []).filter((s) => s.id !== gone.id);
      toast(`${gone.name} is removed from the catalog.`, "ok");
    } catch (e) {
      if (!sessionGone(e)) toast(e instanceof ApiError ? e.message : "Something went wrong.", "critical");
    }
  }
</script>

<svelte:head><title>{pageTitle("Standard services")}</title></svelte:head>

<main class="page-content">
  <div class="page-header">
    <div>
      <h1 class="title">Standard services</h1>
      <p class="small muted">
        What every customer's services start from. A customer gets a copy of a standard service to
        fill in, add to or leave details out of; changing one here never rewrites those copies.
      </p>
    </div>
    {#if mayKeep}
      <button class="button button-accent" type="button" onclick={() => edit()}>
        <Plus size={18} aria-hidden="true" />Add a service
      </button>
    {/if}
  </div>

  {#if error && !open}<p class="alert alert-critical" role="alert">{error}</p>{/if}

  {#if services}
    <ul class="catalog">
      {#each services as service (service.id)}
        <li class="section">
          <div class="head">
            <div>
              <h2 class="section-title">{service.name}</h2>
              <p class="small muted">{service.description || "No description"}</p>
            </div>
            <Pill tone="neutral" text={service.used_by === 1 ? "1 customer" : `${service.used_by} customers`} />
            {#if mayKeep}
              <RowMenu label="Actions for {service.name}" items={[
                { label: "Change service", icon: Pencil, run: () => edit(service) },
                ...(service.key === "support" ? [] : [{ label: "Remove service", icon: Trash, danger: true,
                  run: () => { removing = service; removeOpen = true; } }]),
              ]} />
            {/if}
          </div>
          {#if service.details.length}
            <ul class="details">
              {#each service.details as detail (detail.key)}
                <li>
                  <span>{detail.label}</span>
                  <span class="small muted">{DETAIL_KINDS[detail.kind]}{detail.kind === "choice" ? `: ${detail.choices.join(", ")}` : ""}</span>
                </li>
              {/each}
            </ul>
          {:else}
            <p class="small muted">No details yet.</p>
          {/if}
        </li>
      {/each}
    </ul>
  {/if}
</main>

<Dialog bind:open size="wide" title={draft.id === null ? "Add a service" : `Change ${draft.name}`}>
  {#if open}
    <form class="stack" onsubmit={save}>
      {#if error}<p class="alert alert-critical" role="alert">{error}</p>{/if}
      <div class="field-grid">
        <div class="field">
          <label for="service-name">Name</label>
          <input id="service-name" class="input" required maxlength="100" bind:value={draft.name} />
        </div>
        <div class="field description">
          <label for="service-description">Description</label>
          <input id="service-description" class="input" maxlength="500" bind:value={draft.description} />
        </div>
      </div>
      <fieldset class="checks">
        <legend class="check-title">Details worth recording</legend>
        {#each draft.details as detail, n (n)}
          <div class="detail-row" class:choice={detail.kind === "choice"}>
            <div class="field label">
              <label for="detail-label-{n}">Detail</label>
              <input id="detail-label-{n}" class="input" required maxlength="80" bind:value={detail.label} />
            </div>
            <div class="field kind">
              <label for="detail-kind-{n}">Kind</label>
              <select id="detail-kind-{n}" class="input" bind:value={detail.kind}>
                {#each Object.entries(DETAIL_KINDS) as [value, name] (value)}<option {value}>{name}</option>{/each}
              </select>
            </div>
            {#if detail.kind === "choice"}
              <div class="field choices">
                <label for="detail-choices-{n}">Choices</label>
                <input id="detail-choices-{n}" class="input" required placeholder="Separated by commas" bind:value={detail.choiceText} />
              </div>
            {/if}
            <div class="field help">
              <label for="detail-help-{n}">Help</label>
              <input id="detail-help-{n}" class="input" maxlength="200" bind:value={detail.help} />
            </div>
            <button class="icon-button remove" type="button" aria-label="Remove {detail.label || 'this detail'}"
              onclick={() => draft.details.splice(n, 1)}><X size={16} aria-hidden="true" /></button>
          </div>
        {/each}
        <div><button class="button button-secondary" type="button" onclick={addDetail}>
          <Plus size={16} aria-hidden="true" />Add a detail
        </button></div>
      </fieldset>
      <div class="button-row end">
        <button class="button button-secondary" type="button" onclick={() => (open = false)}>Cancel</button>
        <button class="button button-primary" type="submit" disabled={busy}>Save service</button>
      </div>
    </form>
  {/if}
</Dialog>

<Dialog bind:open={removeOpen} title="Remove {removing?.name ?? ''}">
  <p>
    It's removed from the catalog. Customers who have it keep their copy, with what was filled in.
  </p>
  {#snippet actions()}
    <button class="button button-secondary" type="button" onclick={() => (removeOpen = false)}>Cancel</button>
    <button class="button button-primary" type="button" onclick={remove}>Remove service</button>
  {/snippet}
</Dialog>

<style>
  .catalog {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
    gap: var(--space-4);
    margin: 0;
    padding: 0;
    list-style: none;
  }
  .head {
    display: flex;
    align-items: flex-start;
    gap: var(--space-2);
  }
  .head > div {
    flex: 1 1 auto;
  }
  .head p {
    margin: 0;
  }
  .details {
    display: flex;
    flex-direction: column;
    margin: var(--space-3) 0 0;
    padding: 0;
    list-style: none;
  }
  .details li {
    display: flex;
    justify-content: space-between;
    gap: var(--space-3);
    padding: var(--space-2) 0;
    border-top: 1px solid var(--border);
    font: var(--type-body-sm);
  }
  /* The name, and the description in the rest of its line. */
  .field-grid > .description {
    grid-column: 2 / -1;
  }
  /* A detail to a line: what it's called, its kind, the choices if it has any, and
     the help shown under it. Where the dialog is narrow, over two or three lines. */
  .detail-row {
    display: grid;
    grid-template-columns: minmax(0, 1.2fr) minmax(0, 0.8fr) minmax(0, 1fr) minmax(0, 1.4fr) 44px;
    grid-template-areas: "label kind help help remove";
    gap: var(--space-2) var(--space-3);
    align-items: end;
    padding: var(--space-3) 0;
    border-top: 1px solid var(--border);
  }
  .detail-row.choice {
    grid-template-areas: "label kind choices help remove";
  }
  legend + .detail-row {
    padding-top: 0;
    border-top: 0;
  }
  .label { grid-area: label; }
  .kind { grid-area: kind; }
  .choices { grid-area: choices; }
  .help { grid-area: help; }
  .remove {
    grid-area: remove;
    width: 44px;
    height: 46px;
  }
  @container dialog (max-width: 760px) {
    .field-grid > .description {
      grid-column: 1 / -1;
    }
    .detail-row {
      grid-template-columns: minmax(0, 2fr) minmax(0, 1fr) 44px;
      grid-template-areas:
        "label kind remove"
        "help help help";
    }
    .detail-row.choice {
      grid-template-areas:
        "label kind remove"
        "choices choices choices"
        "help help help";
    }
  }
  /* On a phone the kind gets a line of its own, so its name is read in full. */
  @container dialog (max-width: 420px) {
    .detail-row {
      grid-template-columns: minmax(0, 1fr) 44px;
      grid-template-areas:
        "label remove"
        "kind kind"
        "help help";
    }
    .detail-row.choice {
      grid-template-areas:
        "label remove"
        "kind kind"
        "choices choices"
        "help help";
    }
  }
  .end {
    justify-content: flex-end;
  }
</style>
