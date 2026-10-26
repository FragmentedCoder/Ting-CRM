<script lang="ts">
  import { goto } from "$app/navigation";
  import { resolve } from "$app/paths";
  import { onMount } from "svelte";
  import { api, ApiError } from "#lib/api.js";
  import { pageTitle } from "#lib/branding.svelte.js";
  import CustomerFields from "#lib/components/CustomerFields.svelte";
  import { type CustomerDetail } from "#lib/customers.js";
  import { can, session } from "#lib/session.svelte.js";
  import { toast } from "#lib/toast.svelte.js";
  import { refreshWorkspace } from "#lib/workspace.svelte.js";

  let form = $state({ name: "", cvr: "", address: "", retention_months: 12 });
  let error = $state<string | null>(null);
  let busy = $state(false);

  onMount(async () => {
    if (!can(session.current, "manage_customers")) await goto(resolve("/(app)/customers"), { replace: true });
  });

  async function submit(event: SubmitEvent) {
    event.preventDefault();
    busy = true;
    error = null;
    try {
      const created = await api<CustomerDetail>("POST", "/customers", form);
      toast(`${created.name} is added, with its own encryption key.`, "ok");
      await refreshWorkspace();
      await goto(resolve("/(app)/customers/[id]", { id: String(created.id) }));
    } catch (e) {
      error = e instanceof ApiError ? e.message : "The customer could not be added.";
    } finally {
      busy = false;
    }
  }
</script>

<svelte:head><title>{pageTitle("Add customer")}</title></svelte:head>

<main class="page-content">
  <div class="page-header">
    <div>
      <a class="small" href={resolve("/(app)/customers")}>Customers</a>
      <h1 class="title">Add customer</h1>
      <p class="small muted">
        Sites, contacts and who works with the customer come next, in the customer's menu.
      </p>
    </div>
  </div>
  <form class="section stack form-wide" onsubmit={submit}>
    {#if error}<p class="alert alert-critical" role="alert">{error}</p>{/if}
    <CustomerFields bind:values={form} />
    <div class="button-row">
      <button class="button button-primary" type="submit" disabled={busy}>Add customer</button>
      <a class="button button-secondary" href={resolve("/(app)/customers")}>Cancel</a>
    </div>
  </form>
</main>

<style>
  .form-wide {
    max-width: 640px;
  }
</style>
