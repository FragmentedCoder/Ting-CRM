<script lang="ts">
  import CircleCheck from "@lucide/svelte/icons/circle-check";
  import CircleMinus from "@lucide/svelte/icons/circle-minus";
  import CircleX from "@lucide/svelte/icons/circle-x";
  import RefreshCw from "@lucide/svelte/icons/refresh-cw";
  import TriangleAlert from "@lucide/svelte/icons/triangle-alert";
  import { onMount } from "svelte";
  import { api, ApiError } from "#lib/api.js";
  import { pageTitle } from "#lib/branding.svelte.js";
  import Pill from "#lib/components/Pill.svelte";
  import { bytes, dateTime, since } from "#lib/format.js";
  import { toast } from "#lib/toast.svelte.js";

  type Status = "ok" | "warning" | "problem" | "off";

  interface Check {
    key: string;
    label: string;
    status: Status;
    detail: string;
  }

  interface StampRun {
    id: number;
    state: "queued" | "running" | "done" | "failed";
    result: { seq?: number } | null;
    error: string | null;
  }

  interface Health {
    checked_at: string;
    started_at: string;
    address: string;
    setup_completed_at: string | null;
    checks: string[];
    usage: {
      disk_total_bytes: number;
      disk_free_bytes: number;
      database_bytes: number;
      images_bytes: number;
      audit_entries: number;
      users: number;
      active_users: number;
      sessions: number;
    };
    versions: {
      ting: string;
      python: string;
      sqlite: string;
      sqlcipher: string;
      schema_version: string | null;
      operating_system: string;
      kernel: string;
    };
    packages: { name: string; version: string }[];
  }

  // Shown at once; each fills in when its own request answers. "clock" is
  // worked out here, from the server's time against this computer's.
  const ROWS = [
    { key: "database", label: "Database" },
    { key: "audit_chain", label: "Audit log" },
    { key: "audit_stamps", label: "Audit log timestamp" },
    { key: "keys", label: "Keys" },
    { key: "disk", label: "Disk space" },
    { key: "breach_check", label: "Breached-password check" },
    { key: "worker", label: "Background worker" },
    { key: "backups", label: "Backups" },
    { key: "restore_test", label: "Restore test" },
    { key: "clock", label: "Clock" },
  ];
  const PILLS: Record<Status, { tone: "ok" | "warning" | "critical" | "neutral"; text: string }> = {
    ok: { tone: "ok", text: "OK" },
    warning: { tone: "warning", text: "Warning" },
    problem: { tone: "critical", text: "Problem" },
    off: { tone: "neutral", text: "Off" },
  };
  // At a glance: a check mark when all is well, a cross when it isn't.
  const ICONS = {
    ok: { icon: CircleCheck, class: "is-ok" },
    warning: { icon: TriangleAlert, class: "is-warning" },
    problem: { icon: CircleX, class: "is-problem" },
    off: { icon: CircleMinus, class: "is-off" },
  } as const;
  // Authenticator codes change every 30 seconds; a server clock this far off breaks them.
  const CLOCK_TOLERANCE_S = 30;

  let health = $state<Health | null>(null);
  // The audit log's daily timestamp: which authority, and asking for one now.
  let tsaUrl = $state("");
  let stamping = $state(false);
  let results = $state<Record<string, Check | { failed: string }>>({});
  let pending = $state<Record<string, boolean>>({});
  let error = $state<string | null>(null);

  const checking = $derived(Object.values(pending).some(Boolean));
  const statuses = $derived(
    Object.values(results).flatMap((r) => ("status" in r ? [r.status] : ["problem"])),
  );
  const summary = $derived.by(() => {
    if (checking) return { tone: "neutral" as const, text: "Checking…" };
    if (statuses.includes("problem")) return { tone: "critical" as const, text: "Needs action" };
    if (statuses.includes("warning")) return { tone: "warning" as const, text: "Needs a look" };
    return { tone: "ok" as const, text: "All OK" };
  });

  function clockCheck(found: Health, asked: number, answered: number): Check {
    const off = Math.abs(Math.round((Date.parse(found.checked_at) - (asked + answered) / 2) / 1000));
    return off > CLOCK_TOLERANCE_S
      ? {
          key: "clock",
          label: "Clock",
          status: "warning",
          detail: `The server's clock and this computer's differ by ${off} seconds. Authenticator codes need the server's clock to be right.`,
        }
      : { key: "clock", label: "Clock", status: "ok", detail: "The server's clock matches this computer's." };
  }

  async function runCheck(key: string) {
    pending[key] = true;
    try {
      results[key] = await api<Check>("GET", `/admin/health/checks/${key}`);
    } catch (e) {
      results[key] = { failed: e instanceof ApiError ? e.message : "The check didn't answer." };
    } finally {
      pending[key] = false;
    }
  }

  async function loadInfo() {
    pending.clock = true;
    try {
      const asked = Date.now();
      const found = await api<Health>("GET", "/admin/health");
      results.clock = clockCheck(found, asked, Date.now());
      health = found;
    } catch (e) {
      error = e instanceof ApiError ? e.message : "The server could not be checked.";
    } finally {
      pending.clock = false;
    }
  }

  // Everything starts at once; the last answers stay on screen until new ones arrive.
  function check() {
    error = null;
    void loadInfo();
    for (const row of ROWS) if (row.key !== "clock") void runCheck(row.key);
  }

  onMount(() => {
    check();
    void api<{ tsa_url: string }>("GET", "/audit/verify").then((chain) => (tsaUrl = chain.tsa_url),
      () => {});
  });

  // Ask the worker for a timestamp now, and follow it until it's done.
  async function stampNow() {
    stamping = true;
    try {
      let run = await api<StampRun>("POST", "/audit/stamps/run");
      while ((run.state === "queued" && !run.error) || run.state === "running") {
        await new Promise((done) => setTimeout(done, 2000));
        run = await api<StampRun>("GET", `/audit/stamps/runs/${run.id}`);
      }
      if (run.state === "done") toast(`Timestamped entry ${run.result?.seq}.`, "ok");
      else toast(run.error ?? "The timestamp couldn't be had.", "critical");
      await runCheck("audit_stamps");
    } catch (e) {
      toast(e instanceof ApiError ? e.message : "Something went wrong.", "critical");
    } finally {
      stamping = false;
    }
  }

  async function saveAuthority(event: SubmitEvent) {
    event.preventDefault();
    try {
      const chain = await api<{ tsa_url: string }>("PUT", "/audit/stamps/authority", { tsa_url: tsaUrl });
      tsaUrl = chain.tsa_url;
      toast("Timestamp authority saved.", "ok", { key: "saved" });
      await runCheck("audit_stamps");
    } catch (e) {
      toast(e instanceof ApiError ? e.message : "Something went wrong.", "critical");
    }
  }
</script>

<svelte:head><title>{pageTitle("Server health · Admin")}</title></svelte:head>

{#snippet value(text: string | number | null | undefined, mono = false)}
  {#if health}<span class:mono>{text ?? "—"}</span>{:else}<span class="muted">…</span>{/if}
{/snippet}

<div class="page-header">
  <div>
    <h1 class="title">Server health</h1>
    <p class="small muted">
      {health ? `Checked ${dateTime(health.checked_at)}.` : "Checking the server…"}
      Each check runs on its own, so the slow ones hold up nothing.
    </p>
  </div>
  <button class="button button-secondary" type="button" disabled={checking} onclick={check}>
    <RefreshCw size={16} aria-hidden="true" />
    {checking ? "Checking…" : "Check again"}
  </button>
</div>

{#if error}<p class="alert alert-critical" role="alert">{error}</p>{/if}

<section class="section" aria-labelledby="checks-title">
  <div class="heading-row">
    <h2 class="section-title" id="checks-title">Checks</h2>
    <Pill tone={summary.tone} text={summary.text} />
  </div>
  <p class="small muted">
    Whether the database, the audit log and the keys are intact, and whether there's room and
    a connection for what Þing needs.
  </p>
  <table class="checks-table">
    <tbody>
      {#each ROWS as row (row.key)}
        {@const result = results[row.key]}
        <tr aria-busy={pending[row.key] ?? false}>
          <th scope="row">
            <span class="check-label">
              {#if !pending[row.key] && result}
                {@const shown = ICONS["status" in result ? result.status : "problem"]}
                <shown.icon class="mark {shown.class}" size={18} aria-hidden="true" />
              {/if}
              {row.label}
            </span>
            <span class="small muted detail">
              {#if result && "status" in result}
                {result.detail}
              {:else if result}
                {result.failed}
              {:else}
                Checking…
              {/if}
            </span>
          </th>
          <td class="status">
            {#if pending[row.key] || !result}
              <Pill tone="neutral" text="Checking…" />
            {:else if "status" in result}
              <Pill tone={PILLS[result.status].tone} text={PILLS[result.status].text} />
            {:else}
              <Pill tone="critical" text="No answer" />
            {/if}
          </td>
        </tr>
      {/each}
    </tbody>
  </table>
</section>

<section class="section stack" aria-labelledby="stamps-title">
  <h2 class="section-title" id="stamps-title">The audit log's timestamps</h2>
  <p class="small muted">
    Once a day the worker has a timestamp authority sign a fingerprint of the newest entry, so
    a log cut short shows even though its chain still holds. Only the fingerprint leaves the
    server. The checks above say whether the chain and every timestamp still match.
  </p>
  <div>
    <button class="button button-secondary" type="button" disabled={stamping} onclick={stampNow}>
      {stamping ? "Timestamping…" : "Timestamp now"}
    </button>
  </div>
  <details class="authority">
    <summary class="small">Timestamp authority</summary>
    <form class="authority-form stack" onsubmit={saveAuthority}>
      <div class="field">
        <label for="tsa">Address of an RFC 3161 timestamp authority</label>
        <input id="tsa" class="input" type="url" required maxlength="300" bind:value={tsaUrl} />
        <span class="hint">
          Free ones include DigiCert's (http://timestamp.digicert.com) and FreeTSA
          (https://freetsa.org/tsr).
        </span>
      </div>
      <div><button class="button button-secondary" type="submit">Save</button></div>
    </form>
  </details>
</section>

<section class="section" aria-labelledby="space-title">
  <h2 class="section-title" id="space-title">Space</h2>
  <p class="small muted">How full the server's disk is, and what Þing keeps on it.</p>
  <div class="disk">
    <span class="check-label" id="disk-label">Disk</span>
    {#if health}
      <meter aria-labelledby="disk-label" min="0" max={health.usage.disk_total_bytes}
        value={health.usage.disk_total_bytes - health.usage.disk_free_bytes}
        high={health.usage.disk_total_bytes * 0.85} optimum="0"></meter>
      <p class="small muted">
        {bytes(health.usage.disk_free_bytes)} free of {bytes(health.usage.disk_total_bytes)}
      </p>
    {:else}
      <meter aria-labelledby="disk-label" min="0" max="1"></meter>
      <p class="small muted">…</p>
    {/if}
  </div>
  <dl class="facts">
    <dt>Database</dt>
    <dd>{@render value(health && bytes(health.usage.database_bytes))}</dd>
    <dt>Pictures and logo</dt>
    <dd>{@render value(health && bytes(health.usage.images_bytes))}</dd>
    <dt>Audit log</dt>
    <dd>{@render value(health && `${health.usage.audit_entries.toLocaleString("en-GB")} entries`)}</dd>
    <dt>Users</dt>
    <dd>{@render value(health && `${health.usage.active_users} active of ${health.usage.users}`)}</dd>
    <dt>Signed-in sessions</dt>
    <dd>{@render value(health?.usage.sessions)}</dd>
  </dl>
</section>

<section class="section" aria-labelledby="server-title">
  <h2 class="section-title" id="server-title">Server</h2>
  <dl class="facts">
    <dt>Address</dt>
    <dd>{@render value(health?.address, true)}</dd>
    <dt>Running for</dt>
    <dd>
      {@render value(
        health && `${since(health.started_at)} (since ${dateTime(health.started_at)})`,
      )}
    </dd>
    <dt>Set up</dt>
    <dd>{@render value(health && dateTime(health.setup_completed_at, "Not finished"))}</dd>
  </dl>
</section>

<section class="section" aria-labelledby="versions-title">
  <h2 class="section-title" id="versions-title">Software</h2>
  <p class="small muted">The versions running now, for support questions and update checks.</p>
  <dl class="facts">
    <dt>Þing</dt>
    <dd>{@render value(health?.versions.ting, true)}</dd>
    <dt>Database schema</dt>
    <dd>{@render value(health?.versions.schema_version, true)}</dd>
    <dt>Python</dt>
    <dd>{@render value(health?.versions.python, true)}</dd>
    <dt>SQLite</dt>
    <dd>{@render value(health?.versions.sqlite, true)}</dd>
    <dt>SQLCipher</dt>
    <dd>{@render value(health?.versions.sqlcipher, true)}</dd>
    <dt>Operating system</dt>
    <dd>{@render value(health?.versions.operating_system)}</dd>
    <dt>Kernel</dt>
    <dd>{@render value(health?.versions.kernel, true)}</dd>
  </dl>
  {#if health}
    <details>
      <summary>Python packages ({health.packages.length})</summary>
      <div class="table-wrap">
        <table class="table">
          <thead><tr><th>Package</th><th>Version</th></tr></thead>
          <tbody>
            {#each health.packages as item (item.name)}
              <tr><td class="mono">{item.name}</td><td class="mono">{item.version}</td></tr>
            {/each}
          </tbody>
        </table>
      </div>
    </details>
  {/if}
</section>

<style>
  .heading-row {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-3);
  }
  .checks-table {
    width: 100%;
    border-collapse: collapse;
  }
  .checks-table th,
  .checks-table td {
    padding: var(--space-3) 0;
    border-top: 1px solid var(--border);
    vertical-align: top;
  }
  .checks-table tr:first-child th,
  .checks-table tr:first-child td {
    border-top: 0;
  }
  .checks-table th {
    font-weight: inherit;
    text-align: left;
  }
  .check-label {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    font: var(--type-label);
  }
  .check-label :global(.mark) {
    flex: none;
  }
  .check-label :global(.is-ok) {
    color: var(--ok-text);
  }
  .check-label :global(.is-warning) {
    color: var(--warning-text);
  }
  .check-label :global(.is-problem) {
    color: var(--critical-text);
  }
  .check-label :global(.is-off) {
    color: var(--text-muted);
  }
  .authority-form {
    max-width: 520px;
    margin-top: var(--space-3);
  }
  .detail {
    display: block;
  }
  .status {
    width: 1%;
    padding-left: var(--space-4);
    text-align: right;
    white-space: nowrap;
  }
  .disk {
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
    max-width: 520px;
  }
  meter {
    width: 100%;
    height: 12px;
  }
  details {
    margin-top: var(--space-2);
  }
  summary {
    font: var(--type-label);
    cursor: pointer;
  }
</style>
