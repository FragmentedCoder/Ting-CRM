<script lang="ts">
  import { goto } from "$app/navigation";
  import { resolve } from "$app/paths";
  import { onMount } from "svelte";
  import { pageTitle } from "#lib/branding.svelte.js";
  import AuthLayout from "#lib/components/AuthLayout.svelte";
  import SaveSecrets from "#lib/components/SaveSecrets.svelte";
  import SecondFactorSetup from "#lib/components/SecondFactorSetup.svelte";
  import { recoveryCodesText } from "#lib/secrets.js";
  import {
    settle,
    signOut,
    useSession,
    type SecondFactorResult,
    type SessionInfo,
  } from "#lib/session.svelte.js";

  let info = $state<SessionInfo | null>(null);
  let codes = $state<string[] | null>(null);

  onMount(async () => {
    info = await settle("/sign-in/set-up");
  });

  function done(result: SecondFactorResult) {
    useSession(result.session);
    codes = result.recovery_codes ?? [];
  }
</script>

<svelte:head><title>{pageTitle("Set up multifactor")}</title></svelte:head>

{#if info && codes === null}
  <AuthLayout
    heading="Set up multifactor"
    intro="Your account needs more than a password: Þing asks for one of these every time you sign in. Choose how you want to confirm it's you."
  >
    <SecondFactorSetup onDone={done} />
    {#snippet footer()}
      <button class="link-button" type="button" onclick={signOut}>Sign out</button>
    {/snippet}
  </AuthLayout>
{:else if info && codes}
  <AuthLayout
    heading="Save your recovery codes"
    intro="If you lose your phone or key, each code lets you sign in once. They are shown only now."
  >
    <SaveSecrets
      text={recoveryCodesText(info.user.username, codes)}
      filename="ting-recovery-codes.txt"
      confirmation="I have saved these codes somewhere safe"
      onContinue={() => goto(resolve("/(app)"))}
    >
      <ol class="codes mono">
        {#each codes as code (code)}<li>{code}</li>{/each}
      </ol>
    </SaveSecrets>
  </AuthLayout>
{/if}
