<script lang="ts">
  // Where backups go (one place or several), when and for how long: the admin panel's
  // Backups page and the setup wizard. Secrets are typed here and sent once; the
  // server never sends them back.
  import { hourLabel, KINDS, newTarget, type PlanForm, type TargetKind } from "#lib/backups.js";

  let { plan = $bindable() }: { plan: PlanForm } = $props();

  const HOURS = Array.from({ length: 24 }, (_, hour) => hour);
  // Each target gets every backup on its own; this server can be one of them once.
  const MAX_TARGETS = 5;
  const hasLocal = $derived(plan.targets.some((target) => target.kind === "local"));

  // A new place starts as the first kind not used yet (any can be changed).
  function add() {
    const used = new Set(plan.targets.map((target) => target.kind));
    const kind: TargetKind = (["local", "smb", "s3"] as const).find((k) => !used.has(k)) ?? "smb";
    plan.targets.push(newTarget(kind));
  }

  function remove(index: number) {
    plan.targets.splice(index, 1);
  }

  function title(index: number): string {
    return plan.targets.length > 1 ? `Place ${index + 1}` : "Backup target";
  }
</script>

{#each plan.targets as target, index (index)}
  <fieldset class="target stack">
    <legend class="check-title">{title(index)}</legend>
    <div class="checks kinds" role="radiogroup" aria-label="{title(index)}: kind">
      {#each KINDS as option (option.kind)}
        <label class="check">
          <input type="radio" name="kind-{index}" value={option.kind} bind:group={target.kind}
            disabled={option.kind === "local" && hasLocal && target.kind !== "local"} />
          <span>
            <span class="check-title">{option.name}</span>
            <span class="small muted">{option.about}</span>
          </span>
        </label>
      {/each}
    </div>

    {#if target.kind === "smb"}
      <div class="grid">
        <div class="field">
          <label for="smb-host-{index}">Server</label>
          <input id="smb-host-{index}" class="input" required bind:value={target.smb_host} />
          <span class="hint">Its name or address, such as “nas.example.internal”.</span>
        </div>
        <div class="field">
          <label for="smb-share-{index}">Share</label>
          <input id="smb-share-{index}" class="input" required bind:value={target.smb_share} />
        </div>
        <div class="field">
          <label for="smb-path-{index}">Folder in the share</label>
          <input id="smb-path-{index}" class="input" bind:value={target.smb_path} />
        </div>
        <div class="field">
          <label for="smb-domain-{index}">Domain (optional)</label>
          <input id="smb-domain-{index}" class="input" bind:value={target.smb_domain} />
        </div>
        <div class="field">
          <label for="smb-user-{index}">User name</label>
          <input id="smb-user-{index}" class="input" required autocomplete="off" bind:value={target.smb_username} />
        </div>
        <div class="field">
          <label for="smb-password-{index}">Password</label>
          <input id="smb-password-{index}" class="input" type="password" autocomplete="new-password"
            placeholder={target.secretSet ? "Saved; type to replace it" : ""} bind:value={target.secret} />
        </div>
      </div>
    {:else if target.kind === "s3"}
      <div class="grid">
        <div class="field wide">
          <label for="s3-endpoint-{index}">Address</label>
          <input id="s3-endpoint-{index}" class="input" required placeholder="https://s3.eu-north-1.amazonaws.com"
            bind:value={target.s3_endpoint} />
        </div>
        <div class="field">
          <label for="s3-bucket-{index}">Bucket</label>
          <input id="s3-bucket-{index}" class="input" required bind:value={target.s3_bucket} />
        </div>
        <div class="field">
          <label for="s3-path-{index}">Folder in the bucket</label>
          <input id="s3-path-{index}" class="input" bind:value={target.s3_path} />
        </div>
        <div class="field">
          <label for="s3-region-{index}">Region (optional)</label>
          <input id="s3-region-{index}" class="input" bind:value={target.s3_region} />
        </div>
        <div class="field">
          <label for="s3-key-{index}">Access key</label>
          <input id="s3-key-{index}" class="input" required autocomplete="off" bind:value={target.s3_access_key_id} />
        </div>
        <div class="field">
          <label for="s3-secret-{index}">Secret key</label>
          <input id="s3-secret-{index}" class="input" type="password" autocomplete="new-password"
            placeholder={target.secretSet ? "Saved; type to replace it" : ""} bind:value={target.secret} />
        </div>
      </div>
    {:else if plan.targets.length === 1}
      <p class="alert alert-warning">
        Backups kept on this server don't survive losing it. Add an SMB share or S3-compatible
        storage as well, or point TING_BACKUP_DIR at a separate disk.
      </p>
    {/if}

    <div>
      <button class="button button-secondary" type="button" onclick={() => remove(index)}>
        Remove {plan.targets.length > 1 ? `place ${index + 1}` : "it"}
      </button>
    </div>
  </fieldset>
{:else}
  <p class="alert alert-warning">Backups are off: nothing is being backed up.</p>
{/each}

{#if plan.targets.length < MAX_TARGETS}
  <div>
    <button class="button button-secondary" type="button" onclick={add}>
      {plan.targets.length ? "Add another place" : "Add a place to back up to"}
    </button>
  </div>
{/if}

{#if plan.targets.length}
  <h3 class="subtitle">When and for how long</h3>
  <div class="grid">
    <div class="field">
      <label for="hour">Every night at</label>
      <select id="hour" class="input" bind:value={plan.hour}>
        {#each HOURS as hour (hour)}
          <option value={hour}>{hourLabel(hour)}</option>
        {/each}
      </select>
    </div>
    <div class="field">
      <label for="keep">Keep for (days)</label>
      <input id="keep" class="input" type="number" min="7" max="3650" required bind:value={plan.keep_days} />
    </div>
  </div>
  <p class="small muted">
    Every place gets each backup. Older snapshots are deleted: a customer deleted in Þing
    stays in older snapshots until they age out, and after {plan.keep_days} days no backup
    holds anything of them.
  </p>
{/if}

<style>
  .target {
    margin: 0;
    padding: var(--space-4);
    border: 1px solid var(--border);
    border-radius: var(--radius-md);
  }
  .kinds {
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
  .wide {
    grid-column: 1 / -1;
  }
  .subtitle {
    margin: var(--space-2) 0 0;
    font: var(--type-label);
  }
</style>
