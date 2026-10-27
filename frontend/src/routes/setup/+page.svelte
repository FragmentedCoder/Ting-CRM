<script lang="ts">
  import { goto } from "$app/navigation";
  import { resolve } from "$app/paths";
  import { onMount } from "svelte";
  import { api, ApiError } from "#lib/api.js";
  import { planBody, planForm, type BackupRun, type BackupStatus, type PlanForm } from "#lib/backups.js";
  import AuthLayout from "#lib/components/AuthLayout.svelte";
  import BackupPlanFields from "#lib/components/BackupPlanFields.svelte";
  import MailFields from "#lib/components/MailFields.svelte";
  import TlsFields from "#lib/components/TlsFields.svelte";
  import { mailBody, type MailServer, type MailStatus } from "#lib/mail.js";
  import PolicyFields from "#lib/components/PolicyFields.svelte";
  import SaveSecrets from "#lib/components/SaveSecrets.svelte";
  import SecondFactorSetup from "#lib/components/SecondFactorSetup.svelte";
  import VerifySecondFactor from "#lib/components/VerifySecondFactor.svelte";
  import type { SecuritySettings } from "#lib/policy.js";
  import { branding } from "#lib/branding.svelte.js";
  import Command from "#lib/components/Command.svelte";
  import { recoveryCodesText, recoveryKitText, type RecoveryKit } from "#lib/secrets.js";
  import { choiceFrom, tlsBody, type TlsChoice, type TlsStatus } from "#lib/tls.js";
  import {
    session,
    settle,
    useSession,
    type SecondFactorResult,
    type SessionInfo,
  } from "#lib/session.svelte.js";

  type Step =
    | "token"
    | "company"
    | "security"
    | "administrator"
    | "sign-in"
    | "second-factor"
    | "verify"
    | "codes"
    | "kit"
    | "backups"
    | "email"
    | "tls";
  type LaterStep = "backups" | "email" | "tls";
  const STEP_COUNT = 9;
  const STEP_NUMBER: Record<Step, number> = {
    token: 1,
    company: 2,
    security: 3,
    administrator: 4,
    "sign-in": 4,
    "second-factor": 5,
    verify: 5,
    codes: 5,
    kit: 6,
    backups: 7,
    email: 8,
    tls: 9,
  };

  interface Progress {
    company_name: string | null;
    address: string;
    security_reviewed: boolean;
    security: SecuritySettings;
    administrator: string | null;
    kit_saved: boolean;
    steps_done: LaterStep[];
  }

  let ready = $state(false);
  let step = $state<Step>("token");
  let token = $state("");
  let progress = $state<Progress | null>(null);
  let companyName = $state("");
  let security = $state<SecuritySettings | null>(null);
  let admin = $state({ display_name: "", username: "", email: "", password: "", repeat: "" });
  let password = $state("");
  let codes = $state<string[]>([]);
  let kit = $state<RecoveryKit | null>(null);
  let backups = $state<BackupStatus | null>(null);
  let backupPlan = $state<PlanForm | null>(null);
  let checking = $state(false);
  let checkFailed = $state(false);
  let mail = $state<MailStatus | null>(null);
  let mailServer = $state<MailServer | null>(null);
  let mailPassword = $state("");
  let testTo = $state("");
  let tls = $state<TlsStatus | null>(null);
  let tlsChoice = $state<TlsChoice | null>(null);
  let notice = $state<string | null>(null);
  let error = $state<string | null>(null);
  let breachCheckDown = $state(false);
  let busy = $state(false);

  const eyebrow = $derived(`Step ${STEP_NUMBER[step]} of ${STEP_COUNT}`);
  const tokenHeader = $derived({ "X-Setup-Token": token });

  onMount(async () => {
    await settle("/setup");
    ready = session.setupNeeded;
  });

  async function run<T>(action: () => Promise<T>): Promise<T | null> {
    busy = true;
    error = null;
    try {
      return await action();
    } catch (e) {
      if (e instanceof ApiError && e.status === 410) {
        session.setupNeeded = false; // finished in another window
        await goto(resolve("/(app)"));
        return null;
      }
      error = e instanceof ApiError ? e.message : "Something went wrong. Try again.";
      return null;
    } finally {
      busy = false;
    }
  }

  /** Where setup stands decides the next step, so a reload or a second visit resumes. */
  function nextStep() {
    const current = session.current;
    error = null;
    if (!progress) step = "token";
    else if (!progress.company_name) step = "company";
    else if (!progress.security_reviewed) step = "security";
    else if (!progress.administrator) step = "administrator";
    else if (current?.user.username !== progress.administrator) step = "sign-in";
    else if (current.second_factor === "enrol") step = "second-factor";
    else if (current.second_factor === "verify") step = "verify";
    else if (!progress.kit_saved) void showKit();
    else if (!progress.steps_done.includes("backups")) void showBackups();
    else if (!progress.steps_done.includes("email")) void showEmail();
    else if (!progress.steps_done.includes("tls")) void showTls();
    else void finish();
  }

  function stepDone(done: LaterStep) {
    if (progress && !progress.steps_done.includes(done)) progress.steps_done.push(done);
    nextStep();
  }

  async function submitToken(event: SubmitEvent) {
    event.preventDefault();
    const found = await run(() => api<Progress>("POST", "/setup/progress", undefined, tokenHeader));
    if (!found) return;
    progress = found;
    companyName = found.company_name ?? "";
    security = { ...found.security };
    nextStep();
  }

  async function submitCompany(event: SubmitEvent) {
    event.preventDefault();
    const found = await run(() =>
      api<Progress>("POST", "/setup/company", { name: companyName }, tokenHeader),
    );
    if (!found) return;
    progress = found;
    nextStep();
  }

  async function submitSecurity(event: SubmitEvent) {
    event.preventDefault();
    const found = await run(() =>
      api<Progress>("POST", "/setup/security", security, tokenHeader),
    );
    if (!found) return;
    progress = found;
    nextStep();
  }

  async function createAdministrator(skipBreachCheck: boolean) {
    if (admin.password !== admin.repeat) {
      error = "The two passwords don't match.";
      return;
    }
    breachCheckDown = false;
    const info = await run(async () => {
      try {
        return await api<SessionInfo>(
          "POST",
          "/setup/administrator",
          {
            display_name: admin.display_name,
            username: admin.username,
            email: admin.email || null,
            password: admin.password,
            skip_breach_check: skipBreachCheck,
          },
          tokenHeader,
        );
      } catch (e) {
        if (e instanceof ApiError && e.status === 503) breachCheckDown = true;
        throw e;
      }
    });
    if (!info) return;
    useSession(info);
    if (progress) progress.administrator = info.user.username;
    admin.password = admin.repeat = "";
    nextStep();
  }

  async function submitSignIn(event: SubmitEvent) {
    event.preventDefault();
    const info = await run(() =>
      api<SessionInfo>("POST", "/auth/sign-in", { username: progress?.administrator, password }),
    );
    password = "";
    if (!info) return;
    useSession(info);
    nextStep();
  }

  function secondFactorDone(result: SecondFactorResult) {
    useSession(result.session);
    codes = result.recovery_codes ?? [];
    if (codes.length) step = "codes";
    else nextStep();
  }

  function verified(result: SecondFactorResult) {
    useSession(result.session);
    nextStep();
  }

  async function showKit() {
    step = "kit";
    kit = await run(() => api<RecoveryKit>("POST", "/setup/recovery-kit", undefined, tokenHeader));
  }

  async function kitSaved() {
    const found = await run(() => api<Progress>("POST", "/setup/kit-saved", undefined, tokenHeader));
    if (!found) return;
    progress = found;
    kit = null;
    nextStep();
  }

  // The later steps start from what's saved (the admin panel's API: the
  // administrator is signed in by now), and save through the wizard's.
  async function showBackups() {
    step = "backups";
    checkFailed = false;
    backups = await run(() => api<BackupStatus>("GET", "/admin/backups"));
    if (backups) backupPlan = planForm(backups);
  }

  async function showEmail() {
    step = "email";
    notice = null;
    mail = await run(() => api<MailStatus>("GET", "/admin/email"));
    if (mail) mailServer = { ...mail.server };
    testTo ||= admin.email;
  }

  async function showTls() {
    step = "tls";
    tls = await run(() => api<TlsStatus>("GET", "/admin/tls"));
    if (tls) tlsChoice = choiceFrom(tls);
  }

  async function later(skipped: LaterStep) {
    const found = await run(() =>
      api<Progress>("POST", `/setup/later/${skipped}`, undefined, tokenHeader),
    );
    if (!found) return;
    progress = found;
    nextStep();
  }

  /** Ask the worker to reach each place backups go; what went wrong in words, or null
   * when it reached them all. */
  async function checkConnections(): Promise<string | null> {
    const words = new Map(backups?.targets.map((t) => [t.target.id, t.words]) ?? []);
    let checks = await api<BackupRun[]>("POST", "/admin/backups/run/backup_check");
    const failures: string[] = [];
    for (let tries = 0; tries < 45 && checks.length; tries++) {
      const still: BackupRun[] = [];
      for (const check of checks) {
        if (check.state === "failed" || (check.state === "queued" && check.error)) {
          failures.push(`${words.get(check.target) ?? check.target}: ${check.error ?? "the check failed"}`);
        } else if (check.state !== "done") {
          still.push(check);
        }
      }
      if (!still.length) break;
      await new Promise((wait) => setTimeout(wait, 2000));
      checks = await Promise.all(still.map((check) =>
        api<BackupRun>("GET", `/admin/backups/runs/${check.id}`)));
    }
    if (checks.some((check) => check.state === "queued" && !check.error || check.state === "running")) {
      failures.push("the worker didn't get to it within 90 seconds. Is it running?");
    }
    return failures.length ? failures.join("; ") : null;
  }

  async function saveBackups(event: SubmitEvent) {
    event.preventDefault();
    if (!backupPlan) return;
    const saved = await run(() =>
      api<BackupStatus>("POST", "/setup/backups", planBody(backupPlan!), tokenHeader),
    );
    if (!saved) return;
    backups = saved;
    backupPlan = planForm(saved);
    if (saved.targets.some((t) => t.target.kind !== "local")) {
      checking = true;
      const failure = await run(checkConnections);
      checking = false;
      if (failure) {
        checkFailed = true;
        error = `Saved, but Þing couldn't reach ${failure}`;
        return;
      }
    }
    stepDone("backups");
  }

  async function saveEmail(sendTest: boolean) {
    if (!mailServer) return;
    const saved = await run(() =>
      api<MailStatus>("POST", "/setup/email", mailBody(mailServer!, mailPassword), tokenHeader),
    );
    if (!saved) return;
    mail = saved;
    mailPassword = "";
    if (!sendTest) {
      stepDone("email");
      return;
    }
    notice = null;
    const sent = await run(() => api("POST", "/admin/email/test", { to: testTo }));
    if (sent !== null) notice = `Test message sent to ${testTo}. Check that it arrived.`;
  }

  async function saveTls(event: SubmitEvent) {
    event.preventDefault();
    if (!tlsChoice) return;
    // Finish straight after: Caddy takes the new certificate within a few seconds.
    const saved = await run(() => api<TlsStatus>("POST", "/setup/tls", tlsBody(tlsChoice!), tokenHeader));
    if (!saved) return;
    tls = saved;
    stepDone("tls");
  }

  async function finish() {
    const done = await run(() => api("POST", "/setup/complete", undefined, tokenHeader));
    if (!done) return;
    session.setupNeeded = false;
    await goto(resolve("/(app)"));
  }
</script>

<svelte:head><title>Set up {branding.current.site_name}</title></svelte:head>

{#if ready}
  {#if step === "token"}
    <AuthLayout heading="Set up Þing" {eyebrow}>
      <p class="muted">
        The installer printed a one-time setup token, so only someone with access to the
        server can set Þing up. If it's gone from the screen, print a new one on the server
        (the old one stops working):
      </p>
      <Command command="sudo ting setup-token" />
      <form class="stack" onsubmit={submitToken}>
        {#if error}<p class="alert alert-critical" role="alert">{error}</p>{/if}
        <div class="field">
          <label for="token">Setup token</label>
          <input
            id="token"
            class="input code"
            autocomplete="off"
            autocapitalize="characters"
            spellcheck="false"
            required
            bind:value={token}
          />
        </div>
        <button class="button button-primary button-block" type="submit" disabled={busy}>
          Continue
        </button>
      </form>
    </AuthLayout>
  {:else if step === "company" && progress}
    <AuthLayout
      heading="Company and server"
      intro="Þing works for one company. Its name appears in the app and on every report."
      {eyebrow}
    >
      <div class="address stack">
        <p class="check-title">Server address</p>
        <p class="mono">{progress.address}</p>
        <p class="small muted">
          Passkeys are tied to this address. If it isn't the one people will use, stop here,
          set <span class="mono">TING_ADDRESS</span> on the server and restart Þing.
        </p>
      </div>
      <form class="stack" onsubmit={submitCompany}>
        {#if error}<p class="alert alert-critical" role="alert">{error}</p>{/if}
        <div class="field">
          <label for="company">Company name</label>
          <input
            id="company"
            class="input"
            autocomplete="organization"
            required
            bind:value={companyName}
          />
        </div>
        <button class="button button-primary button-block" type="submit" disabled={busy}>
          Continue
        </button>
      </form>
    </AuthLayout>
  {:else if step === "security" && security}
    <AuthLayout
      heading="Security settings"
      intro="These defaults suit most teams. You can change them any time under Admin, Security."
      {eyebrow}
    >
      <form class="stack" onsubmit={submitSecurity}>
        {#if error}<p class="alert alert-critical" role="alert">{error}</p>{/if}
        <PolicyFields bind:values={security} />
        <button class="button button-primary button-block" type="submit" disabled={busy}>
          Continue
        </button>
      </form>
    </AuthLayout>
  {:else if step === "administrator"}
    <AuthLayout heading="Create the administrator" {eyebrow}>
      <p class="muted">
        This is the break-glass account: it works even when your directory is down, and every
        sign-in with it is flagged in the audit log. Use it for setup and emergencies, and give
        people their own accounts for daily work.
      </p>
      <form
        class="stack"
        onsubmit={(event) => {
          event.preventDefault();
          createAdministrator(false);
        }}
      >
        {#if breachCheckDown}
          <div class="alert alert-warning stack" role="alert">
            <p>
              Þing couldn't reach api.pwnedpasswords.com to check the password against known
              data breaches. If this server has no internet access, you can continue without the
              check.
            </p>
            <button
              class="button button-secondary"
              type="button"
              disabled={busy}
              onclick={() => createAdministrator(true)}
            >
              Continue without the check
            </button>
          </div>
        {:else if error}
          <p class="alert alert-critical" role="alert">{error}</p>
        {/if}
        <div class="field">
          <label for="display-name">Full name</label>
          <input
            id="display-name"
            class="input"
            autocomplete="name"
            required
            bind:value={admin.display_name}
          />
        </div>
        <div class="field">
          <label for="username">Username</label>
          <input
            id="username"
            class="input"
            autocomplete="username"
            autocapitalize="none"
            spellcheck="false"
            required
            bind:value={admin.username}
          />
        </div>
        <div class="field">
          <label for="email">Email (optional)</label>
          <input
            id="email"
            class="input"
            type="email"
            autocomplete="email"
            bind:value={admin.email}
          />
        </div>
        <div class="field">
          <label for="password">Password</label>
          <input
            id="password"
            class="input"
            type="password"
            autocomplete="new-password"
            aria-describedby="password-hint"
            required
            bind:value={admin.password}
          />
          <span class="hint" id="password-hint">
            At least 12 characters. A few random words work well.
          </span>
        </div>
        <div class="field">
          <label for="repeat">Repeat password</label>
          <input
            id="repeat"
            class="input"
            type="password"
            autocomplete="new-password"
            required
            bind:value={admin.repeat}
          />
        </div>
        <button class="button button-primary button-block" type="submit" disabled={busy}>
          Create administrator
        </button>
      </form>
    </AuthLayout>
  {:else if step === "sign-in" && progress}
    <AuthLayout
      heading="Sign in as {progress.administrator}"
      intro="The administrator for this server is already created. Sign in to continue setup."
      {eyebrow}
    >
      <form class="stack" onsubmit={submitSignIn}>
        {#if error}<p class="alert alert-critical" role="alert">{error}</p>{/if}
        <div class="field">
          <label for="admin-password">Password</label>
          <input
            id="admin-password"
            class="input"
            type="password"
            autocomplete="current-password"
            required
            bind:value={password}
          />
        </div>
        <button class="button button-primary button-block" type="submit" disabled={busy}>
          Sign in
        </button>
      </form>
    </AuthLayout>
  {:else if step === "second-factor" && session.current}
    <AuthLayout
      heading="Protect the administrator"
      intro="The administrator always signs in with multifactor authentication. Set it up for {session
        .current.user.username} now."
      {eyebrow}
    >
      <SecondFactorSetup onDone={secondFactorDone} />
    </AuthLayout>
  {:else if step === "verify" && session.current}
    <AuthLayout heading="Confirm it's you" {eyebrow}>
      <VerifySecondFactor info={session.current} onDone={verified} />
    </AuthLayout>
  {:else if step === "codes" && session.current}
    <AuthLayout
      heading="Save your recovery codes"
      intro="If you lose your phone or key, each code lets you sign in once. They are shown only now."
      {eyebrow}
    >
      <SaveSecrets
        text={recoveryCodesText(session.current.user.username, codes)}
        filename="ting-recovery-codes.txt"
        confirmation="I have saved these codes somewhere safe"
        onContinue={nextStep}
      >
        <ol class="codes mono">
          {#each codes as code (code)}<li>{code}</li>{/each}
        </ol>
      </SaveSecrets>
    </AuthLayout>
  {:else if step === "kit"}
    <AuthLayout heading="Save the recovery kit" {eyebrow}>
      <p class="muted">
        These two keys unlock this server's data and its backups. Without them, no backup can be
        restored. Keep them offline or in your password manager, never on this server. They are
        shown only during setup.
      </p>
      {#if error}<p class="alert alert-critical" role="alert">{error}</p>{/if}
      {#if kit}
        <SaveSecrets
          text={recoveryKitText(kit)}
          filename="ting-recovery-kit.txt"
          confirmation="I have saved the recovery kit somewhere safe, away from this server"
          {busy}
          onContinue={kitSaved}
        >
          <dl class="kit">
            <dt>Master key</dt>
            <dd class="mono">{kit.master_key}</dd>
            <dt>Backup key</dt>
            <dd class="mono">{kit.backup_key}</dd>
          </dl>
        </SaveSecrets>
      {/if}
    </AuthLayout>
  {:else if step === "backups"}
    <AuthLayout
      heading="Where backups go"
      intro="Every night, encrypted with the backup key from the recovery kit. You can change this any time under Admin, Backups."
      {eyebrow}
      wide
    >
      {#if error}<p class="alert alert-critical" role="alert">{error}</p>{/if}
      {#if backups && backupPlan}
        <form class="stack" onsubmit={saveBackups}>
          <BackupPlanFields bind:plan={backupPlan} />
          {#if checking}<p class="small" role="status">Checking that Þing can reach it…</p>{/if}
          <div class="button-row">
            <button class="button button-primary" type="submit" disabled={busy}>
              {backupPlan.targets.some((t) => t.kind !== "local") ? "Save and check" : "Save and continue"}
            </button>
            {#if checkFailed}
              <button class="button button-secondary" type="button" disabled={busy}
                onclick={() => stepDone("backups")}>Continue anyway</button>
            {:else}
              <button class="button button-secondary" type="button" disabled={busy}
                onclick={() => later("backups")}>Set up later</button>
            {/if}
          </div>
        </form>
      {/if}
    </AuthLayout>
  {:else if step === "email"}
    <AuthLayout
      heading="Email"
      intro="The mail server Þing sends reports and notices through. You can change this any time under Admin, Email."
      {eyebrow}
      wide
    >
      {#if error}<p class="alert alert-critical" role="alert">{error}</p>{/if}
      {#if notice}<p class="alert alert-ok" role="status">{notice}</p>{/if}
      {#if mail && mailServer}
        <form
          class="stack"
          onsubmit={(event) => {
            event.preventDefault();
            saveEmail(false);
          }}
        >
          <MailFields bind:server={mailServer} bind:password={mailPassword}
            passwordSet={mail.password_set} />
          <div class="test">
            <div class="field">
              <label for="test-to">Send a test message to (optional)</label>
              <input id="test-to" class="input" type="email" autocomplete="email" bind:value={testTo} />
            </div>
            <button class="button button-secondary" type="button" disabled={busy || !testTo}
              onclick={() => saveEmail(true)}>Save and send a test</button>
          </div>
          <div class="button-row">
            <button class="button button-primary" type="submit" disabled={busy}>Save and continue</button>
            <button class="button button-secondary" type="button" disabled={busy}
              onclick={() => later("email")}>Set up later</button>
          </div>
        </form>
      {/if}
    </AuthLayout>
  {:else if step === "tls"}
    <AuthLayout
      heading="Certificate"
      intro="What browsers see at {tls?.host ?? 'this address'}. You can change it any time under Admin, Certificate."
      {eyebrow}
      wide
    >
      {#if error}<p class="alert alert-critical" role="alert">{error}</p>{/if}
      {#if tls && tlsChoice}
        <form class="stack" onsubmit={saveTls}>
          <TlsFields bind:choice={tlsChoice} host={tls.host} uploaded={tls.settings.certificate}
            tokenSet={tls.cloudflare_token_set} keySet={tls.rfc2136_key_set} />
          {#if tlsChoice.mode === "internal" && tls.root_url}
            <p class="small">
              <!-- eslint-disable-next-line svelte/no-navigation-without-resolve -- a file Caddy serves, not a page -->
              <a href={tls.root_url} download="ting-root.crt">Download the root certificate</a>
              and install it as a trusted root on each computer that will use Þing: this one
              too, if the browser warned about the certificate.
            </p>
          {/if}
          <div class="button-row">
            <button class="button button-primary" type="submit" disabled={busy}>Save and finish setup</button>
            <button class="button button-secondary" type="button" disabled={busy}
              onclick={() => later("tls")}>Set up later and finish</button>
          </div>
        </form>
      {/if}
    </AuthLayout>
  {/if}
{/if}

<style>
  .address {
    gap: var(--space-1);
    padding: var(--space-4);
    border-radius: var(--radius-md);
    background: var(--surface-subtle);
  }
  .kit {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    margin: 0;
    padding: var(--space-4);
    border-radius: var(--radius-md);
    background: var(--surface-subtle);
  }
  .kit dt {
    font: var(--type-label);
  }
  .kit dd {
    margin: 0 0 var(--space-2);
    overflow-wrap: normal;
  }
  .test {
    display: flex;
    flex-wrap: wrap;
    align-items: flex-end;
    gap: var(--space-3);
  }
  .test .field {
    flex: 1 1 240px;
  }
</style>
