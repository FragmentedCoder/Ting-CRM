<script lang="ts">
  import { goto } from "$app/navigation";
  import { resolve } from "$app/paths";
  import ImageIcon from "@lucide/svelte/icons/image";
  import { api, ApiError, sessionGone } from "#lib/api.js";
  import { pageTitle } from "#lib/branding.svelte.js";
  import CustomerFields from "#lib/components/CustomerFields.svelte";
  import Dialog from "#lib/components/Dialog.svelte";
  import { sharedCustomer } from "#lib/context.js";
  import RowMenu from "#lib/components/RowMenu.svelte";
  import Pencil from "@lucide/svelte/icons/pencil";
  import Plus from "@lucide/svelte/icons/plus";
  import Trash from "@lucide/svelte/icons/trash-2";
  import { STATUS_NAMES, formatCvr, type Company, type CustomerDetail, type CustomerStatus } from "#lib/customers.js";
  import { withStepUp } from "#lib/stepUp.svelte.js";
  import { toast } from "#lib/toast.svelte.js";
  import { refreshWorkspace } from "#lib/workspace.svelte.js";

  // The customer's own details, for everyone who may change them; its status, how long
  // its records are kept and its logo for Administrators and Managers; deleting it for
  // Administrators.
  const shared = sharedCustomer();
  const customer = $derived(shared.current);
  let details = $state({ name: "", cvr: "", address: "", retention_months: 12 });
  let status = $state<CustomerStatus>("active");
  let statusDate = $state("");
  let logoInput = $state<HTMLInputElement>();
  let busy = $state(false);
  let deleteOpen = $state(false);
  let deleteName = $state("");
  let deleteError = $state<string | null>(null);

  $effect(() => {
    if (!customer) return;
    details = {
      name: customer.name,
      cvr: customer.cvr ?? "",
      address: customer.address ?? "",
      retention_months: customer.retention_months ?? 12,
    };
    status = customer.status ?? "active";
    statusDate = customer.status_date ?? "";
  });

  async function run(action: () => Promise<CustomerDetail>, done: string): Promise<boolean> {
    busy = true;
    try {
      shared.use(await action());
      toast(done, "ok", { key: "saved" });
      return true;
    } catch (e) {
      if (!sessionGone(e)) toast(e instanceof ApiError ? e.message : "Something went wrong.", "critical");
      return false;
    } finally {
      busy = false;
    }
  }

  function save(event: SubmitEvent) {
    event.preventDefault();
    run(() => api("PATCH", `/customers/${customer?.id}`, details), "Details saved.");
  }

  function saveStatus(event: SubmitEvent) {
    event.preventDefault();
    const body = { status, status_date: status === "active" ? null : statusDate || null };
    run(() => api("PATCH", `/customers/${customer?.id}`, body), "Status saved.");
  }

  // The group's other companies.
  let companyOpen = $state(false);
  let company = $state<{ id: number | null; name: string; cvr: string; address: string }>(
    { id: null, name: "", cvr: "", address: "" });

  function editCompany(found?: Company) {
    company = found ? { id: found.id, name: found.name, cvr: found.cvr ?? "", address: found.address }
      : { id: null, name: "", cvr: "", address: "" };
    companyOpen = true;
  }

  async function saveCompany(event: SubmitEvent) {
    event.preventDefault();
    const { id: companyId, ...fields } = company;
    const body = { ...fields, cvr: fields.cvr.trim() || null };
    const base = `/customers/${customer?.id}/companies`;
    const saved = await run(() => companyId === null ? api("POST", base, body)
      : api("PUT", `${base}/${companyId}`, body), "Company saved.");
    if (saved) companyOpen = false;
  }

  function uploadLogo() {
    const file = logoInput?.files?.[0];
    if (logoInput) logoInput.value = "";
    if (file) run(() => api("PUT", `/customers/${customer?.id}/logo`, file), "Logo saved.");
  }

  async function deleteCustomer(event: SubmitEvent) {
    event.preventDefault();
    busy = true;
    deleteError = null;
    try {
      await withStepUp(() => api("DELETE", `/customers/${customer?.id}`, { confirm_name: deleteName }));
      toast(`${customer?.name} is deleted, and its key with it.`, "ok");
      // Away from its pages first, so they don't take it for lost access.
      await goto(resolve("/(app)/customers"));
      await refreshWorkspace();
    } catch (e) {
      if (e instanceof ApiError && e.reason === "step_up_cancelled") return;
      if (!sessionGone(e)) deleteError = e instanceof ApiError ? e.message : "The customer could not be deleted.";
    } finally {
      busy = false;
    }
  }
</script>

<svelte:head><title>{pageTitle(`Customer settings · ${customer?.name ?? "Customer"}`)}</title></svelte:head>

{#if customer && !customer.may_edit}
  <p class="alert alert-warning">
    Only Administrators, Managers and technicians change a customer's details.
  </p>
{:else if customer}
  <section class="section" aria-labelledby="details-title">
    <h2 class="section-title" id="details-title">Details</h2>
    <p class="small muted">
      Everything here is encrypted with the customer's own key.
    </p>
    <form class="stack form-wide" onsubmit={save}>
      <CustomerFields bind:values={details} retention={customer.may_manage} />
      <div><button class="button button-primary" type="submit" disabled={busy}>Save details</button></div>
    </form>
  </section>

  <section class="section" aria-labelledby="companies-title">
    <div class="heading-row">
      <h2 class="section-title" id="companies-title">Companies in the group</h2>
      <button class="button button-secondary" type="button" onclick={() => editCompany()}>
        <Plus size={16} aria-hidden="true" />Add a company
      </button>
    </div>
    <p class="small muted">
      A group with subsidiaries is one customer: the details above are its main company.
    </p>
    {#if customer.companies?.length}
      <ul class="companies">
        {#each customer.companies as item (item.id)}
          <li>
            <div>
              <p class="check-title">{item.name}</p>
              <p class="small muted mono">{item.cvr ? `CVR ${formatCvr(item.cvr)}` : "No CVR number"}</p>
            </div>
            <RowMenu label="Actions for {item.name}" items={[
              { label: "Change company", icon: Pencil, run: () => editCompany(item) },
              { label: "Remove company", icon: Trash, danger: true,
                run: () => run(() => api("DELETE", `/customers/${customer?.id}/companies/${item.id}`), `${item.name} is removed.`) },
            ]} />
          </li>
        {/each}
      </ul>
    {:else}
      <p class="muted">No other companies.</p>
    {/if}
  </section>

  <Dialog bind:open={companyOpen} title={company.id === null ? "Add a company" : "Change company"}>
    <form class="stack" onsubmit={saveCompany}>
      <CustomerFields bind:values={company} retention={false} legal="The company's legal name, such as a subsidiary's." />
      <div class="button-row end">
        <button class="button button-secondary" type="button" onclick={() => (companyOpen = false)}>Cancel</button>
        <button class="button button-primary" type="submit" disabled={busy}>Save company</button>
      </div>
    </form>
  </Dialog>

  {#if customer.may_manage}
  <section class="section" aria-labelledby="status-title">
    <h2 class="section-title" id="status-title">Status</h2>
    <p class="small muted">
      A departing customer leaves on the day given; a former one has left, and its records are
      kept for the months set above from that day.
    </p>
    <form class="stack form-wide" onsubmit={saveStatus}>
      <div class="field">
        <label for="customer-status">Status</label>
        <select id="customer-status" class="input status" bind:value={status}>
          {#each Object.entries(STATUS_NAMES) as [value, name] (value)}
            <option {value}>{name}</option>
          {/each}
        </select>
      </div>
      {#if status !== "active"}
        <div class="field">
          <label for="customer-status-date">{status === "departing" ? "Leaves on" : "Left on"}</label>
          <input id="customer-status-date" class="input status" type="date" required
            bind:value={statusDate} />
        </div>
      {/if}
      <div><button class="button button-primary" type="submit" disabled={busy}>Save status</button></div>
    </form>
  </section>

  <section class="section" aria-labelledby="logo-title">
    <h2 class="section-title" id="logo-title">Logo</h2>
    <p class="small muted">Shown beside the customer's name. A PNG, JPEG, WebP or GIF up to 2 MB.</p>
    <input bind:this={logoInput} class="visually-hidden" type="file"
      accept="image/png,image/jpeg,image/webp,image/gif" onchange={uploadLogo} />
    <div class="button-row">
      <button class="button button-secondary" type="button" disabled={busy} onclick={() => logoInput?.click()}>
        <ImageIcon size={16} aria-hidden="true" />
        {customer.logo_url ? "Replace logo" : "Upload a logo"}
      </button>
      {#if customer.logo_url}
        <button class="button button-secondary" type="button" disabled={busy}
          onclick={() => run(() => api("DELETE", `/customers/${customer?.id}/logo`), "Logo removed.")}>
          Remove logo
        </button>
      {/if}
    </div>
  </section>
  {/if}

  {#if customer.may_delete}
    <section class="section danger-zone" aria-labelledby="delete-title">
      <h2 class="section-title" id="delete-title">Delete customer</h2>
      <p class="small">
        Deletes the customer, its sites and contacts, and its encryption key: whatever was
        encrypted with it can't be read again. This can't be undone.
      </p>
      <div>
        <button class="button button-secondary danger" type="button"
          onclick={() => { deleteName = ""; deleteError = null; deleteOpen = true; }}>
          Delete customer
        </button>
      </div>
    </section>

    <Dialog bind:open={deleteOpen} title="Delete {customer.name}">
      <form class="stack" onsubmit={deleteCustomer}>
        {#if deleteError}<p class="alert alert-critical" role="alert">{deleteError}</p>{/if}
        <p>
          Its sites and contacts go too, with its encryption key, so nothing that was encrypted
          with it can be read again. This can't be undone.
        </p>
        <div class="field">
          <label for="delete-name">Type the customer's name to confirm</label>
          <input id="delete-name" class="input" autocomplete="off" required bind:value={deleteName} />
        </div>
        <div class="button-row end">
          <button class="button button-secondary" type="button" onclick={() => (deleteOpen = false)}>Cancel</button>
          <button class="button button-primary danger-fill" type="submit"
            disabled={busy || deleteName.trim() !== customer.name}>Delete for good</button>
        </div>
      </form>
    </Dialog>
  {/if}
{/if}

<style>
  .status {
    max-width: 16rem;
  }
  .heading-row {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-3);
  }
  .companies {
    display: flex;
    flex-direction: column;
    margin: 0;
    padding: 0;
    list-style: none;
  }
  .companies li {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-3);
    padding: var(--space-2) 0;
    border-top: 1px solid var(--border);
  }
  .companies p {
    margin: 0;
  }
  .end {
    justify-content: flex-end;
  }
  .form-wide {
    max-width: 640px;
  }
  .end {
    justify-content: flex-end;
  }
  .danger-zone {
    border-color: var(--critical-text);
  }
  .danger {
    border-color: var(--critical-text);
    color: var(--critical-text);
  }
  .danger-fill {
    background: var(--critical-text);
    color: var(--surface);
  }
</style>
