<script lang="ts">
  // The mail server Þing sends through: the admin panel's Email page and the setup
  // wizard. The password is sent once and never comes back.
  import { SECURITY, type MailServer } from "#lib/mail.js";

  let {
    server = $bindable(),
    password = $bindable(),
    passwordSet = false,
  }: { server: MailServer; password: string; passwordSet?: boolean } = $props();

  // Picking how the connection is secured moves a usual port to its usual port.
  function secure(event: Event) {
    const picked = (event.currentTarget as HTMLSelectElement).value;
    const usual = SECURITY.find((option) => option.value === picked)?.port;
    if (usual && SECURITY.some((option) => option.port === server.port)) server.port = usual;
  }
</script>

<div class="grid">
  <div class="field wide">
    <label for="mail-host">Mail server</label>
    <input id="mail-host" class="input" required autocomplete="off" spellcheck="false"
      placeholder="smtp.example.com" bind:value={server.host} />
  </div>
  <div class="field">
    <label for="mail-security">Connection security</label>
    <select id="mail-security" class="input" bind:value={server.security} onchange={secure}>
      {#each SECURITY as option (option.value)}
        <option value={option.value}>{option.name}</option>
      {/each}
    </select>
  </div>
  <div class="field">
    <label for="mail-port">Port</label>
    <input id="mail-port" class="input" type="number" min="1" max="65535" required bind:value={server.port} />
  </div>
  <div class="field">
    <label for="mail-user">User name (optional)</label>
    <input id="mail-user" class="input" autocomplete="off" spellcheck="false" bind:value={server.username} />
  </div>
  <div class="field">
    <label for="mail-password">Password</label>
    <input id="mail-password" class="input" type="password" autocomplete="new-password"
      placeholder={passwordSet ? "Saved; type to replace it" : ""} bind:value={password} />
  </div>
  <div class="field">
    <label for="mail-from">Mail comes from</label>
    <input id="mail-from" class="input" type="email" required placeholder="ting@example.com"
      bind:value={server.from_address} />
  </div>
  <div class="field">
    <label for="mail-name">Sender name (optional)</label>
    <input id="mail-name" class="input" placeholder="Þing" bind:value={server.from_name} />
  </div>
</div>
{#if server.security === "none"}
  <p class="alert alert-warning">
    Without encryption, the password and every message cross the network readable. Use it only
    for a relay on this server's own network.
  </p>
{/if}

<style>
  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
    gap: var(--space-4);
    max-width: 760px;
  }
  .wide {
    grid-column: 1 / -1;
  }
</style>
