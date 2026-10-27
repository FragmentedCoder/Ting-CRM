<script lang="ts">
  import { resolve } from "$app/paths";
  import Circle from "@lucide/svelte/icons/circle";
  import CircleCheck from "@lucide/svelte/icons/circle-check";
  import { pageTitle } from "#lib/branding.svelte.js";
  import { sharedCustomer } from "#lib/context.js";
  import { dateTime } from "#lib/format.js";

  // A customer at a glance: who to talk to, who works with it, the details. What they
  // pay for, coverage, systems and the timeline join it in Phase 2.
  const shared = sharedCustomer();
  const customer = $derived(shared.current);
  const id = $derived(String(customer?.id ?? ""));

  // For administrators, until a new customer is ready for work.
  const steps = $derived(customer ? [
    { label: "Add its contacts and sites", done: !!(customer.contacts?.length || customer.sites?.length),
      href: resolve("/(app)/customers/[id]/contacts", { id }) },
    { label: "Choose who works with it", done: !!customer.assigned?.length,
      href: resolve("/(app)/customers/[id]/people", { id }) },
  ] : []);
  const gettingStarted = $derived(!!customer?.may_manage && steps.some((step) => !step.done));
</script>

<svelte:head><title>{pageTitle(customer?.name ?? "Customer")}</title></svelte:head>

{#if customer}
  <div class="grid">
    {#if gettingStarted}
      <section class="section wide" aria-labelledby="start-title">
        <h2 class="section-title" id="start-title">Getting started</h2>
        <ol class="steps">
          {#each steps as step (step.label)}
            <li class:done={step.done}>
              {#if step.done}
                <CircleCheck size={18} aria-hidden="true" />
                <span>{step.label}<span class="visually-hidden">: done</span></span>
              {:else}
                <Circle size={18} aria-hidden="true" />
                <!-- eslint-disable-next-line svelte/no-navigation-without-resolve -- each step's href comes from resolve() -->
                <a href={step.href}>{step.label}</a>
              {/if}
            </li>
          {/each}
        </ol>
      </section>
    {/if}

    <section class="section" aria-labelledby="contacts-title">
      <h2 class="section-title" id="contacts-title">Contacts</h2>
      {#if customer.contacts?.length}
        <ul class="plain">
          {#each customer.contacts.slice(0, 4) as contact (contact.id)}
            <li>
              <span class="check-title">{contact.name}</span>
              <span class="small muted">{[contact.role, contact.email, contact.phone].filter(Boolean).join(" · ")}</span>
            </li>
          {/each}
        </ul>
      {:else}
        <p class="muted">No contacts yet.</p>
      {/if}
      <a class="small" href={resolve("/(app)/customers/[id]/contacts", { id })}>Contacts & sites</a>
    </section>

    <section class="section" aria-labelledby="people-title">
      <h2 class="section-title" id="people-title">People on this customer</h2>
      {#if customer.assigned?.length}
        <ul class="plain">
          {#each customer.assigned as person (person.id)}
            <li><span class="check-title">{person.display_name}</span></li>
          {/each}
        </ul>
      {:else}
        <p class="muted">Nobody is assigned yet.</p>
      {/if}
      <a class="small" href={resolve("/(app)/customers/[id]/people", { id })}>People</a>
    </section>

    <section class="section wide" aria-labelledby="facts-title">
      <h2 class="section-title" id="facts-title">Details</h2>
      <dl class="facts">
        <dt>Address</dt>
        <dd class="address">{customer.address || "—"}</dd>
        <dt>Sites</dt>
        <dd>{customer.sites?.map((s) => s.name).join(", ") || "—"}</dd>
        <dt>Records kept</dt>
        <dd>{customer.retention_months} months after it stops being a customer</dd>
        <dt>Added</dt>
        <dd>{dateTime(customer.created_at)}</dd>
      </dl>
      <p class="small muted">
        Everything here is encrypted with this customer's own key.
      </p>
    </section>
  </div>
{/if}

<style>
  .grid {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: var(--space-4);
  }
  .wide {
    grid-column: 1 / -1;
  }
  .steps {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    margin: 0;
    padding: 0;
    list-style: none;
  }
  .steps li {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    color: var(--text-muted);
  }
  .steps .done {
    color: var(--ok-text);
  }
  .steps .done span {
    color: var(--text-muted);
    text-decoration: line-through;
  }
  .plain {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    margin: 0;
    padding: 0;
    list-style: none;
  }
  .plain li {
    display: flex;
    flex-direction: column;
  }
  .address {
    white-space: pre-line;
  }
  @media (max-width: 760px) {
    .grid {
      grid-template-columns: minmax(0, 1fr);
    }
  }
</style>
