<script lang="ts">
  import { untrack } from "svelte";
  import { general } from "#lib/general.svelte.js";
  import { codeChoices, joinPhone, splitPhone } from "#lib/phone.js";

  // A phone number: its country code, chosen from a list with the team's own first
  // (Admin → General), and the number after it. Kept as one line of text, as the
  // contact's card shows it: "+45 12 34 56 78". A number already written without a
  // country code keeps none, unless one is chosen.
  let {
    value = $bindable(""),
    id,
    maxlength = 50,
  }: { value?: string; id: string; maxlength?: number } = $props();

  const first = $derived(general.current.phone_country_code);
  let code = $state("");
  let number = $state("");
  let seen: string | null = null;
  let seenFirst = "";

  // Taken apart when the number is another one (the form opens on another contact),
  // and when the team's code arrives while the field is still empty.
  $effect.pre(() => {
    const [text, own] = [value, first];
    untrack(() => {
      if (text !== seen || (own !== seenFirst && text === "" && number === "")) {
        ({ code, number } = splitPhone(text, own));
      }
      seen = text;
      seenFirst = own;
    });
  });

  function changed() {
    // A number typed with its own code takes that code.
    if (/^(\+|00)/.test(number.trim())) ({ code, number } = splitPhone(number, first));
    value = joinPhone(code, number);
    seen = value;
  }
</script>

<div class="phone">
  <select class="input" aria-label="Country code" bind:value={code} onchange={changed}>
    {#each codeChoices(first, code) as choice (choice.code)}
      <option value={choice.code}>{choice.code}{choice.name ? ` ${choice.name}` : ""}</option>
    {/each}
    <option value="">No country code</option>
  </select>
  <input {id} class="input" type="tel" autocomplete="off" maxlength={maxlength - 6} bind:value={number}
    oninput={changed} />
</div>

<style>
  .phone {
    display: grid;
    grid-template-columns: minmax(6.5rem, 11rem) minmax(0, 1fr);
    gap: var(--space-2);
  }
  @container dialog (max-width: 420px) {
    .phone {
      grid-template-columns: minmax(0, 1fr);
    }
  }
</style>
