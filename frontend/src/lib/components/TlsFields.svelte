<script lang="ts">
  // Which certificate Þing serves: the admin panel's Certificate page and the setup
  // wizard. Files are read here and sent once; the key never comes back.
  import Command from "./Command.svelte";
  import { KEY_ALGORITHMS, MODES, RESET_COMMAND, type Certificate, type TlsChoice } from "#lib/tls.js";

  let {
    choice = $bindable(),
    host,
    uploaded = null,
    tokenSet = false,
    keySet = false,
    resetHint = true,
  }: {
    choice: TlsChoice;
    host: string;
    uploaded?: Certificate | null;
    // Whether a Cloudflare token and a TSIG key are saved (never shown).
    tokenSet?: boolean;
    keySet?: boolean;
    // Off where the page shows the way back on its own.
    resetHint?: boolean;
  } = $props();

  let certificateFile = $state("");
  let keyFile = $state("");

  async function read(event: Event, into: "certificate_pem" | "key_pem") {
    const file = (event.currentTarget as HTMLInputElement).files?.[0];
    if (into === "certificate_pem") certificateFile = file?.name ?? "";
    else keyFile = file?.name ?? "";
    choice[into] = file ? await file.text() : "";
  }
</script>

<fieldset class="checks modes">
  <legend class="visually-hidden">Certificate</legend>
  {#each MODES as option (option.mode)}
    <label class="check">
      <input type="radio" name="tls-mode" value={option.mode} bind:group={choice.mode} />
      <span>
        <span class="check-title">{option.name}</span>
        <span class="small muted">{option.about}</span>
      </span>
    </label>
  {/each}
</fieldset>

{#if choice.mode === "own"}
  <div class="grid">
    <div class="field">
      <label for="tls-certificate">Certificate</label>
      <input id="tls-certificate" class="input" type="file" accept=".pem,.crt,.cer"
        required={!uploaded} onchange={(event) => read(event, "certificate_pem")} />
      <span class="hint">For {host}, with any intermediate certificates after it.</span>
    </div>
    <div class="field">
      <label for="tls-key">Private key</label>
      <input id="tls-key" class="input" type="file" accept=".pem,.key"
        required={!uploaded || !!certificateFile} onchange={(event) => read(event, "key_pem")} />
      <span class="hint">Unencrypted, in PEM form. It stays on this server.</span>
    </div>
  </div>
  {#if uploaded && !certificateFile && !keyFile}
    <p class="small muted">
      Saved: {uploaded.subject}, from {uploaded.issuer}. Pick new files to replace it.
    </p>
  {/if}
{:else if choice.mode === "acme"}
  <fieldset class="checks modes">
    <legend class="check-title">How Let's Encrypt checks that {host} is yours</legend>
    <label class="check">
      <input type="radio" name="tls-challenge" value="tls-alpn" bind:group={choice.challenge} />
      <span>
        <span class="check-title">Over the internet</span>
        <span class="small muted">It connects to {host} on port 443, so the internet must reach this server.</span>
      </span>
    </label>
    <label class="check">
      <input type="radio" name="tls-challenge" value="dns" bind:group={choice.challenge} />
      <span>
        <span class="check-title">Through your DNS</span>
        <span class="small muted">Þing puts a record in your DNS for a moment. The server needn't be reachable.</span>
      </span>
    </label>
  </fieldset>
  {#if choice.challenge === "dns"}
    <div class="grid">
      <div class="field">
        <label for="tls-dns">Your DNS is at</label>
        <select id="tls-dns" class="input" bind:value={choice.dns_provider}>
          <option value="cloudflare">Cloudflare</option>
          <option value="rfc2136">Your own DNS server (RFC 2136)</option>
        </select>
      </div>
      {#if choice.dns_provider === "cloudflare"}
        <div class="field">
          <label for="tls-token">API token</label>
          <input id="tls-token" class="input" type="password" autocomplete="off"
            placeholder={tokenSet ? "Saved; type to replace it" : ""} bind:value={choice.cloudflare_token} />
          <span class="hint">One that may edit DNS in the zone of {host} (Zone, DNS, Edit).</span>
        </div>
      {:else}
        <div class="field">
          <label for="tls-server">DNS server</label>
          <input id="tls-server" class="input" spellcheck="false" placeholder="ns1.example.com:53"
            bind:value={choice.rfc2136_server} />
          <span class="hint">The one that takes dynamic updates for the zone of {host}.</span>
        </div>
        <div class="field">
          <label for="tls-key-name">TSIG key name</label>
          <input id="tls-key-name" class="input" spellcheck="false" autocomplete="off"
            bind:value={choice.rfc2136_key_name} />
        </div>
        <div class="field">
          <label for="tls-key-alg">Algorithm</label>
          <select id="tls-key-alg" class="input" bind:value={choice.rfc2136_key_alg}>
            {#each KEY_ALGORITHMS as algorithm (algorithm)}<option value={algorithm}>{algorithm}</option>{/each}
          </select>
        </div>
        <div class="field">
          <label for="tls-tsig">TSIG key</label>
          <input id="tls-tsig" class="input" type="password" autocomplete="off" spellcheck="false"
            placeholder={keySet ? "Saved; type to replace it" : ""} bind:value={choice.rfc2136_key} />
          <span class="hint">Base64, as the DNS server gave it. It stays on this server.</span>
        </div>
      {/if}
    </div>
  {/if}
  <div class="field">
    <label for="tls-email">Email for expiry notices (optional)</label>
    <input id="tls-email" class="input" type="email" autocomplete="email" bind:value={choice.acme_email} />
    <span class="hint">Let's Encrypt writes if renewing fails. Caddy renews on its own.</span>
  </div>
  <p class="alert alert-warning">
    {choice.challenge === "dns"
      ? `${host} must be in public DNS, at the provider above.`
      : `${host} must be reachable from the internet on port 443.`}
    If Let's Encrypt can't check it, there's no certificate and Þing can't be opened{resetHint
      ? ". Then, on the server, run:" : "."}
  </p>
  {#if resetHint}<Command command={RESET_COMMAND} />{/if}
{/if}

<style>
  .modes {
    margin: 0;
    padding: 0;
    border: 0;
  }
  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
    gap: var(--space-4);
    max-width: 760px;
  }
</style>
