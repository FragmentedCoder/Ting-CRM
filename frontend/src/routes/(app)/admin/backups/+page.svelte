<script lang="ts">
  import { onDestroy, onMount } from "svelte";
  import { api, ApiError, sessionGone } from "#lib/api.js";
  import {
    planBody,
    planForm,
    RUN_NAMES,
    runSummary,
    type BackupRun,
    type BackupStatus,
    type PlanForm,
    type RunKind,
  } from "#lib/backups.js";
  import { pageTitle } from "#lib/branding.svelte.js";
  import BackupPlanFields from "#lib/components/BackupPlanFields.svelte";
  import Command from "#lib/components/Command.svelte";
  import Pill from "#lib/components/Pill.svelte";
  import { dateTime } from "#lib/format.js";
  import { withStepUp } from "#lib/stepUp.svelte.js";
  import { toast } from "#lib/toast.svelte.js";

  // Backups: where they go (one place or several), when, for how long, and how they
  // fare. The worker does the work, one job per place; this page queues it and
  // follows it.
  let status = $state<BackupStatus | null>(null);
  let plan = $state<PlanForm | null>(null);
  let error = $state<string | null>(null);
  let busy = $state(false);
  let following = $state<BackupRun[]>([]);
  let timer: ReturnType<typeof setTimeout> | undefined;

  const TONES = { done: "ok", failed: "critical", running: "info", queued: "neutral" } as const;
  const STATES = { done: "OK", failed: "Failed", running: "Running", queued: "Waiting" } as const;

  const words = $derived(new Map(status?.targets.map((t) => [t.target.id, t.words]) ?? []));

  /** Where a run went, as a sentence names it. */
  function where(run: BackupRun): string {
    return (run.target && words.get(run.target)) || run.target || "";
  }

  function capitalised(text: string): string {
    return text.charAt(0).toUpperCase() + text.slice(1);
  }

  function use(found: BackupStatus) {
    status = found;
    plan = planForm(found);
  }

  async function load() {
    try {
      use(await api<BackupStatus>("GET", "/admin/backups"));
    } catch (e) {
      if (!sessionGone(e)) error = e instanceof ApiError ? e.message : "Not available.";
    }
  }

  onMount(load);
  onDestroy(() => clearTimeout(timer));

  async function save(event: SubmitEvent) {
    event.preventDefault();
    if (!plan) return;
    busy = true;
    try {
      use(await withStepUp(() => api<BackupStatus>("PUT", "/admin/backups", planBody(plan!))));
      toast("Backup settings saved.", "ok", { key: "saved" });
    } catch (e) {
      if (e instanceof ApiError && e.reason === "step_up_cancelled") return;
      if (!sessionGone(e)) toast(e instanceof ApiError ? e.message : "Something went wrong.", "critical");
    } finally {
      busy = false;
    }
  }

  // Queue the work (for every place), then ask how it's going every two seconds
  // until each is done.
  async function runNow(kind: RunKind) {
    try {
      const runs = await api<BackupRun[]>("POST", `/admin/backups/run/${kind}`);
      following = [...following, ...runs.filter((run) => !following.some((f) => f.id === run.id))];
      clearTimeout(timer);
      void follow();
    } catch (e) {
      if (!sessionGone(e)) toast(e instanceof ApiError ? e.message : "Something went wrong.", "critical");
    }
  }

  async function follow() {
    const still: BackupRun[] = [];
    for (const waiting of following) {
      const run = await api<BackupRun>("GET", `/admin/backups/runs/${waiting.id}`).catch(() => null);
      if (run && (run.state === "done" || run.state === "failed" || (run.state === "queued" && run.error))) {
        toast(`${RUN_NAMES[run.kind]} to ${where(run)}: ${runSummary(run)}`,
          run.state === "done" ? "ok" : "critical");
      } else {
        still.push(run ?? waiting);
      }
    }
    following = still;
    if (still.length) timer = setTimeout(follow, 2000);
    else await load();
  }
</script>

<svelte:head><title>{pageTitle("Backups · Admin")}</title></svelte:head>

<div class="page-header">
  <div>
    <h1 class="title">Backups</h1>
    <p class="small muted">
      Encrypted with the backup key from the recovery kit: without the kit, a backup can't be
      restored.
    </p>
  </div>
</div>

{#if error}<p class="alert alert-critical" role="alert">{error}</p>{/if}

{#if status && plan}
  <section class="section stack" aria-labelledby="state-title">
    <h2 class="section-title" id="state-title">How it stands</h2>
    {#each status.targets as place (place.target.id)}
      <div class="place">
        <h3 class="subtitle">{capitalised(place.words)}</h3>
        <dl class="facts">
          <dt>Last backup</dt>
          <dd>
            {#if place.last_backup}
              {dateTime(place.last_backup.finished_at)}: {runSummary(place.last_backup)}
            {:else}
              None yet
            {/if}
          </dd>
          <dt>Last restore test</dt>
          <dd>
            {#if place.last_restore_test}
              {dateTime(place.last_restore_test.finished_at)}:
              {place.last_restore_test.state === "done" ? "" : "failed. "}{runSummary(place.last_restore_test)}
            {:else}
              None yet. The worker tests one a week, after a backup.
            {/if}
          </dd>
          <dt>Repository</dt>
          <dd class="mono">{place.repository}</dd>
        </dl>
      </div>
    {/each}
    <dl class="facts">
      <dt>Next backup</dt>
      <dd>
        {#if !status.next_backup_at}
          None: backups are off
        {:else if new Date(status.next_backup_at).getTime() <= Date.now() + 60_000}
          Due now: the worker starts it within a minute
        {:else}
          {dateTime(status.next_backup_at)}
        {/if}
      </dd>
    </dl>
    {#each following as run (run.id)}
      <p class="small" role="status">{RUN_NAMES[run.kind]} to {where(run)}: {runSummary(run)}…</p>
    {/each}
    <div class="button-row">
      <button class="button button-primary" type="button"
        disabled={following.length > 0 || !status.targets.length} onclick={() => runNow("backup")}>
        Back up now
      </button>
      <button class="button button-secondary" type="button"
        disabled={following.length > 0 || !status.targets.some((t) => t.last_backup)}
        onclick={() => runNow("restore_test")}>
        Test a restore now
      </button>
    </div>
  </section>

  <form class="section stack" onsubmit={save} aria-labelledby="target-title">
    <h2 class="section-title" id="target-title">Where backups go</h2>
    <BackupPlanFields bind:plan />

    <div class="button-row">
      <button class="button button-primary" type="submit" disabled={busy}>Save</button>
      <button class="button button-secondary" type="button"
        disabled={following.length > 0 || !status.targets.length} onclick={() => runNow("backup_check")}>
        Check the connections
      </button>
    </div>
    <p class="small muted">Changing where backups go asks you to confirm it's you. The connection check uses what's saved.</p>
  </form>

  <section class="section" aria-labelledby="runs-title">
    <h2 class="section-title" id="runs-title">Recent runs</h2>
    {#if status.runs.length}
      <div class="table-wrap">
        <table class="table">
          <thead><tr><th>When</th><th>What</th><th>Where</th><th>How it went</th><th>Asked for by</th></tr></thead>
          <tbody>
            {#each status.runs as run (run.id)}
              <tr>
                <td class="nowrap">{dateTime(run.finished_at ?? run.started_at ?? run.created_at)}</td>
                <td>{RUN_NAMES[run.kind]}</td>
                <td>{capitalised(where(run))}</td>
                <td>
                  <Pill tone={TONES[run.state]} text={STATES[run.state]} />
                  <span class="small">{runSummary(run)}</span>
                </td>
                <td>{run.requested_by ?? "The schedule"}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    {:else}
      <p class="muted">No runs yet.</p>
    {/if}
  </section>

  <section class="section" aria-labelledby="restore-title">
    <h2 class="section-title" id="restore-title">Restoring</h2>
    <p class="small">
      Restoring replaces Þing's data with a backup, so it's done on the server with the
      recovery kit at hand. Þing stops while it runs, and the data that was there is kept
      beside it.
    </p>
    <Command command="sudo ting restore" />
    <p class="small muted">
      The newest backup unless you add --snapshot and its ID. A backup made before the master
      key was rotated asks for the master key it was made under. On a new server, put the
      kit's master key in place first: run the installer with --restore-master-key.
    </p>
  </section>
{/if}

<style>
  .place + .place {
    padding-top: var(--space-4);
    border-top: 1px solid var(--border);
  }
  .subtitle {
    margin: 0 0 var(--space-2);
    font: var(--type-label);
  }
  .nowrap {
    white-space: nowrap;
  }
</style>
