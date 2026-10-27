<script lang="ts">
  import ImageIcon from "@lucide/svelte/icons/image";
  import { onMount } from "svelte";
  import { api, ApiError, sessionGone } from "#lib/api.js";
  import {
    PROFILE_FIELDS,
    profileForm,
    variableFor,
    type Profile,
    type ProfileForm,
  } from "#lib/admin.js";
  import { branding, pageTitle } from "#lib/branding.svelte.js";
  import { ACCENT, PRIMARY, swatchFor } from "#lib/colours.js";
  import PasswordRules from "#lib/components/PasswordRules.svelte";
  import SwatchPicker from "#lib/components/SwatchPicker.svelte";
  import Avatar from "#lib/components/Avatar.svelte";
  import Dialog from "#lib/components/Dialog.svelte";
  import Pill from "#lib/components/Pill.svelte";
  import SaveSecrets from "#lib/components/SaveSecrets.svelte";
  import SecondFactorSetup from "#lib/components/SecondFactorSetup.svelte";
  import { browserName, date, dateTime } from "#lib/format.js";
  import { recoveryCodesText } from "#lib/secrets.js";
  import { toast } from "#lib/toast.svelte.js";
  import {
    applyTheme,
    session,
    sessionEnded,
    useSession,
    type SecondFactorResult,
    type SessionInfo,
    type Theme,
  } from "#lib/session.svelte.js";

  interface Factor {
    id: number;
    kind: "totp" | "webauthn";
    label: string;
    created_at: string;
    last_used_at: string | null;
  }
  interface SessionRow {
    id: number;
    created_at: string;
    last_seen_at: string;
    ip: string | null;
    user_agent: string | null;
    current: boolean;
  }
  interface Account extends Profile {
    username: string;
    theme: Theme;
    primary_colour: string | null;
    accent_colour: string | null;
    avatar_url: string | null;
    password_changed_at: string | null;
    mfa_required: boolean;
    factors: Factor[];
    recovery_codes_left: number;
    sessions: SessionRow[];
  }

  const KIND_NAMES = { totp: "Authenticator app", webauthn: "Passkey or security key" };

  let info = $state<SessionInfo | null>(null);
  let account = $state<Account | null>(null);
  let profile = $state<ProfileForm | null>(null);
  let theme = $state<Theme>("system");
  let colours = $state({ primary: "", accent: "" });
  let avatarInput = $state<HTMLInputElement>();
  let passwords = $state({ current: "", next: "", repeat: "" });
  let notice = $state<{ section: string; tone: "ok" | "critical"; text: string } | null>(null);
  let busy = $state(false);

  // Re-entering the password guards removing a factor and new recovery codes.
  let confirming = $state<{ title: string; run: (password: string) => Promise<void> } | null>(
    null,
  );
  let confirmOpen = $state(false);
  let confirmPassword = $state("");
  let confirmError = $state<string | null>(null);
  let adding = $state(false);
  let newCodes = $state<string[] | null>(null);
  let codesOpen = $state(false);

  // The last method can't go while the account needs multifactor.
  const lastRequired = $derived(account !== null && account.mfa_required && account.factors.length < 2);

  onMount(async () => {
    info = session.current;
    if (!info) return;
    try {
      await load();
    } catch (e) {
      if (!sessionGone(e)) toast(e instanceof ApiError ? e.message : "Your account couldn't be loaded.", "critical");
    }
  });

  async function load() {
    use(await api<Account>("GET", "/account"));
  }

  function use(found: Account) {
    account = found;
    profile = profileForm(found);
    theme = found.theme;
    colours = { primary: found.primary_colour ?? "", accent: found.accent_colour ?? "" };
    if (session.current) {
      session.current.user.display_name = found.display_name;
      session.current.user.theme = found.theme;
      session.current.user.colours = { primary: found.primary_colour, accent: found.accent_colour };
      session.current.user.avatar_url = found.avatar_url;
    }
  }

  async function guarded(section: string, action: () => Promise<void>) {
    busy = true;
    notice = null;
    try {
      await action();
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) {
        await sessionEnded(e.message, e.reason ?? "");
        return;
      }
      notice = {
        section,
        tone: "critical",
        text: e instanceof ApiError ? e.message : "Something went wrong. Try again.",
      };
    } finally {
      busy = false;
    }
  }

  function saveProfile(event: SubmitEvent) {
    event.preventDefault();
    guarded("profile", async () => {
      use(await api<Account>("PATCH", "/account", profile));
      toast("Your profile is saved.", "ok", { key: "saved" });
    });
  }

  // Appearance applies at once, then saves; a failed save says so.
  async function saveAppearance(fields: { theme?: Theme; primary_colour?: string | null; accent_colour?: string | null }) {
    if (session.current) {
      const user = session.current.user;
      if (fields.theme) user.theme = fields.theme;
      if ("primary_colour" in fields) user.colours.primary = fields.primary_colour ?? null;
      if ("accent_colour" in fields) user.colours.accent = fields.accent_colour ?? null;
    }
    if (fields.theme) applyTheme(fields.theme);
    try {
      use(await api<Account>("PATCH", "/account", fields));
    } catch (e) {
      if (!sessionGone(e)) toast("Couldn't save your appearance. Try again.", "warning", { key: "appearance" });
    }
  }

  const sitePrimary = $derived(swatchFor(branding.current.primary_colour, "primary")?.name ?? "");
  const siteAccent = $derived(swatchFor(branding.current.accent_colour, "accent")?.name ?? "");

  function changePassword(event: SubmitEvent) {
    event.preventDefault();
    if (passwords.next !== passwords.repeat) {
      notice = { section: "password", tone: "critical", text: "The two new passwords don't match." };
      return;
    }
    guarded("password", async () => {
      useSession(
        await api<SessionInfo>("POST", "/account/password", {
          current_password: passwords.current,
          new_password: passwords.next,
        }),
      );
      passwords = { current: "", next: "", repeat: "" };
      await load();
      toast("Your password is changed. Any other sessions were signed out.", "ok");
    });
  }

  function askPassword(title: string, run: (password: string) => Promise<void>) {
    confirming = { title, run };
    confirmPassword = "";
    confirmError = null;
    confirmOpen = true;
  }

  async function confirm(event: SubmitEvent) {
    event.preventDefault();
    if (!confirming) return;
    busy = true;
    confirmError = null;
    try {
      await confirming.run(confirmPassword);
      confirmOpen = false;
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) {
        await sessionEnded(e.message, e.reason ?? "");
        return;
      }
      confirmError = e instanceof ApiError ? e.message : "Something went wrong. Try again.";
    } finally {
      confirmPassword = "";
      busy = false;
    }
  }

  function removeFactor(factor: Factor) {
    askPassword(`Remove “${factor.label}”`, async (password) => {
      account = await api<Account>("POST", `/account/factors/${factor.id}/remove`, { password });
    });
  }

  function regenerateCodes() {
    askPassword("Get new recovery codes", async (password) => {
      const result = await api<{ recovery_codes: string[] }>("POST", "/account/recovery-codes", {
        password,
      });
      newCodes = result.recovery_codes;
      codesOpen = true;
      await load();
    });
  }

  async function factorAdded(result: SecondFactorResult) {
    useSession(result.session);
    adding = false;
    await load();
  }

  function uploadAvatar() {
    const file = avatarInput?.files?.[0];
    if (avatarInput) avatarInput.value = "";
    if (!file) return;
    if (file.size > 2 * 1024 * 1024) {
      notice = { section: "profile", tone: "critical", text: "The picture is larger than 2 MB." };
      return;
    }
    guarded("profile", async () => {
      use(await api<Account>("PUT", "/account/avatar", file));
      toast("Your picture is saved.", "ok", { key: "saved" });
    });
  }

  function removeAvatar() {
    guarded("profile", async () => {
      use(await api<Account>("DELETE", "/account/avatar"));
    });
  }

  function endSession(row: SessionRow) {
    guarded("sessions", async () => {
      account = await api<Account>("POST", `/account/sessions/${row.id}/end`);
      toast(`${browserName(row.user_agent)} is signed out.`, "ok");
    });
  }

  function endOtherSessions() {
    guarded("sessions", async () => {
      account = await api<Account>("POST", "/account/sessions/end-others");
      toast("Your other sessions are signed out.", "ok");
    });
  }
</script>

<svelte:head><title>{pageTitle("Your account")}</title></svelte:head>

{#snippet message(section: string)}
  {#if notice?.section === section}
    <p class="alert alert-{notice.tone}" role={notice.tone === "critical" ? "alert" : "status"}>
      {notice.text}
    </p>
  {/if}
{/snippet}

{#if info && account}
    <main class="page-content">
      <div class="page-header">
        <div>
          <h1 class="title">Your account</h1>
          <p class="small muted">Signed in as <span class="mono">{account.username}</span></p>
        </div>
      </div>

      <section class="section" aria-labelledby="profile-title">
        <h2 class="section-title" id="profile-title">Profile</h2>
        <p class="small muted">
          Work details only, nothing private. Report templates can use them: each field shows its
          name, such as <span class="mono">{variableFor("author", "first_name")}</span> for the
          first name of whoever wrote a report (<span class="mono">reviewer</span> instead of
          <span class="mono">author</span> gives the reviewer's).
        </p>
        {@render message("profile")}
        <div class="picture">
          <Avatar name={account.display_name} url={account.avatar_url} size={72} />
          <div class="stack">
            <input bind:this={avatarInput} class="visually-hidden" type="file" id="avatar-file"
              accept="image/png,image/jpeg,image/webp,image/gif" onchange={uploadAvatar} />
            <div class="button-row">
              <button class="button button-secondary" type="button" disabled={busy}
                onclick={() => avatarInput?.click()}>
                <ImageIcon size={16} aria-hidden="true" />
                {account.avatar_url ? "Change picture" : "Add a picture"}
              </button>
              {#if account.avatar_url}
                <button class="button button-secondary" type="button" disabled={busy}
                  onclick={removeAvatar}>Remove picture</button>
              {/if}
            </div>
            <span class="small muted">A PNG, JPEG, WebP or GIF up to 2 MB.</span>
          </div>
        </div>
        {#if profile}
          <form class="stack form-wide" onsubmit={saveProfile}>
            <div class="field">
              <label for="display-name">Display name</label>
              <input id="display-name" class="input" autocomplete="name" required maxlength="200"
                bind:value={profile.display_name} />
              <span class="hint">
                How Þing shows your name to others.
                <span class="mono">{variableFor("author", "display_name")}</span>
              </span>
            </div>
            <div class="grid">
              {#each PROFILE_FIELDS as field (field.key)}
                <div class="field">
                  <label for={field.key}>{field.label}</label>
                  <input id={field.key} class="input" type={field.type ?? "text"}
                    autocomplete={field.autocomplete} aria-describedby="{field.key}-variable"
                    bind:value={profile[field.key]} />
                  <span class="hint mono" id="{field.key}-variable">{variableFor("author", field.key)}</span>
                </div>
              {/each}
            </div>
            <div><button class="button button-primary" type="submit" disabled={busy}>Save</button></div>
          </form>
        {/if}
      </section>

      <section class="section" aria-labelledby="appearance-title">
        <h2 class="section-title" id="appearance-title">Appearance</h2>
        <p class="small muted">
          How Þing looks for you, on every device you sign in on. Changes apply at once. The
          button beside your name, at the bottom of the side menu, switches between light and
          dark too.
        </p>
        <fieldset class="themes">
          <legend class="check-title">Light or dark</legend>
          {#each [["system", "Same as this device"], ["light", "Light"], ["dark", "Dark"]] as [value, label] (value)}
            <label class="check">
              <input type="radio" name="theme" {value} bind:group={theme}
                onchange={(event) => saveAppearance({ theme: event.currentTarget.value as Theme })} />
              <span>{label}</span>
            </label>
          {/each}
        </fieldset>
        {#if branding.current.enforce_colours}
          <p class="alert alert-info">Your administrator has set the colours for everyone.</p>
        {/if}
        <SwatchPicker legend="Primary colour" hint="Links, buttons, switches and the outline around what has focus."
          swatches={PRIMARY} siteName={sitePrimary} disabled={branding.current.enforce_colours}
          bind:value={() => colours.primary, (next) => { colours.primary = next; saveAppearance({ primary_colour: next || null }); }} />
        <SwatchPicker legend="Accent colour" hint="Marks where you are in the menus, and commands to copy."
          swatches={ACCENT} siteName={siteAccent} disabled={branding.current.enforce_colours}
          bind:value={() => colours.accent, (next) => { colours.accent = next; saveAppearance({ accent_colour: next || null }); }} />
      </section>

      <section class="section" aria-labelledby="password-title">
        <h2 class="section-title" id="password-title">Password</h2>
        <p class="small muted">
          Last changed {dateTime(account.password_changed_at)}. Changing it signs you out
          everywhere else.
        </p>
        <PasswordRules id="password-rules" />
        {@render message("password")}
        <form class="stack form-narrow" onsubmit={changePassword}>
          <input type="text" class="visually-hidden" autocomplete="username"
            value={account.username} readonly tabindex="-1" aria-hidden="true" />
          <div class="field">
            <label for="current-password">Current password</label>
            <input id="current-password" class="input" type="password"
              autocomplete="current-password" required bind:value={passwords.current} />
          </div>
          <div class="field">
            <label for="new-password">New password</label>
            <input id="new-password" class="input" type="password" autocomplete="new-password"
              aria-describedby="password-rules" required bind:value={passwords.next} />
          </div>
          <div class="field">
            <label for="repeat-password">Repeat new password</label>
            <input id="repeat-password" class="input" type="password" autocomplete="new-password"
              required bind:value={passwords.repeat} />
          </div>
          <div>
            <button class="button button-primary" type="submit" disabled={busy}>
              Change password
            </button>
          </div>
        </form>
      </section>

      <section class="section" aria-labelledby="factors-title">
        <h2 class="section-title" id="factors-title">Multifactor authentication</h2>
        <p class="small muted">
          What you use besides your password: an authenticator app, a passkey or a security key.
        </p>
        {@render message("factors")}
        {#if account.factors.length}
          <div class="table-wrap">
            <table class="table">
              <thead>
                <tr><th>Name</th><th>Kind</th><th>Added</th><th>Last used</th><th></th></tr>
              </thead>
              <tbody>
                {#each account.factors as factor (factor.id)}
                  <tr>
                    <td>{factor.label}</td>
                    <td>{KIND_NAMES[factor.kind]}</td>
                    <td>{date(factor.created_at)}</td>
                    <td>{dateTime(factor.last_used_at)}</td>
                    <td class="end">
                      <button class="link-button" type="button" disabled={lastRequired}
                        onclick={() => removeFactor(factor)}>
                        Remove<span class="visually-hidden"> {factor.label}</span>
                      </button>
                    </td>
                  </tr>
                {/each}
              </tbody>
            </table>
          </div>
        {:else}
          <p class="muted">None set up. Your account works with your password alone.</p>
        {/if}
        {#if lastRequired}
          <p class="small muted">Your account needs multifactor: add another before removing this one.</p>
        {/if}
        <div>
          <button class="button button-secondary" type="button" onclick={() => (adding = true)}>
            Add a method
          </button>
        </div>
      </section>

      {#if account.factors.length}
        <section class="section" aria-labelledby="codes-title" id="recovery-codes">
          <h2 class="section-title" id="codes-title">Recovery codes</h2>
          {#if account.recovery_codes_left === 0}
            <div class="alert alert-critical callout" role="alert">
              <p class="check-title">You have no recovery codes left</p>
              <p>
                If you lose your phone or key now, an administrator has to reset your
                multifactor. Get new codes, and keep them somewhere safe.
              </p>
            </div>
          {:else if account.recovery_codes_left <= 3}
            <div class="alert alert-warning callout" role="status">
              <p class="check-title">
                Only {account.recovery_codes_left} recovery {account.recovery_codes_left === 1
                  ? "code"
                  : "codes"} left
              </p>
              <p>Get new codes before you run out. New codes replace all the old ones.</p>
            </div>
          {:else}
            <p><Pill tone="ok" text="{account.recovery_codes_left} of 10 left" /></p>
          {/if}
          <p class="small muted">
            Each code lets you sign in once if you lose your phone or key. New codes replace all
            the old ones.
          </p>
          <div>
            <button class="button {account.recovery_codes_left <= 3 ? 'button-primary' : 'button-secondary'}"
              type="button" onclick={regenerateCodes}>
              Get new codes
            </button>
          </div>
        </section>
      {/if}

      <section class="section" aria-labelledby="sessions-title">
        <h2 class="section-title" id="sessions-title">Where you're signed in</h2>
        <p class="small muted">
          Every browser signed in to your account. If you see one you don't recognise, sign it
          out and change your password.
        </p>
        {@render message("sessions")}
        <div class="table-wrap">
          <table class="table">
            <thead>
              <tr>
                <th>Browser</th><th>Address</th><th>Signed in</th><th>Last active</th>
                <th><span class="visually-hidden">Actions</span></th>
              </tr>
            </thead>
            <tbody>
              {#each account.sessions as row (row.id)}
                <tr>
                  <td>
                    {browserName(row.user_agent)}
                    {#if row.current}<Pill tone="info" text="This browser" />{/if}
                  </td>
                  <td class="mono">{row.ip ?? "—"}</td>
                  <td>{dateTime(row.created_at)}</td>
                  <td>{dateTime(row.last_seen_at)}</td>
                  <td class="end">
                    {#if !row.current}
                      <button class="link-button" type="button" disabled={busy}
                        onclick={() => endSession(row)}>
                        Sign out<span class="visually-hidden">: {browserName(row.user_agent)},
                          signed in {dateTime(row.created_at)}</span>
                      </button>
                    {/if}
                  </td>
                </tr>
              {/each}
            </tbody>
          </table>
        </div>
        <div>
          <button class="button button-secondary" type="button" disabled={busy ||
            account.sessions.length < 2} onclick={endOtherSessions}>
            Sign out all other sessions
          </button>
        </div>
      </section>
    </main>

  <Dialog bind:open={confirmOpen} title={confirming?.title ?? ""}>
    <form class="stack" onsubmit={confirm}>
      {#if confirmError}<p class="alert alert-critical" role="alert">{confirmError}</p>{/if}
      <div class="field">
        <label for="confirm-password">Your password</label>
        <input id="confirm-password" class="input" type="password"
          autocomplete="current-password" required bind:value={confirmPassword} />
        <span class="hint">To make sure it's you.</span>
      </div>
      <div class="button-row">
        <button class="button button-primary" type="submit" disabled={busy}>Confirm</button>
        <button class="button button-secondary" type="button" onclick={() => (confirmOpen = false)}>
          Cancel
        </button>
      </div>
    </form>
  </Dialog>

  <Dialog bind:open={adding} title="Add a multifactor method">
    {#if adding}<SecondFactorSetup onDone={factorAdded} />{/if}
    <div>
      <button class="button button-secondary" type="button" onclick={() => (adding = false)}>
        Cancel
      </button>
    </div>
  </Dialog>

  <Dialog bind:open={codesOpen} title="Your new recovery codes">
    {#if newCodes}
      <SaveSecrets
        text={recoveryCodesText(account.username, newCodes)}
        filename="ting-recovery-codes.txt"
        confirmation="I have saved these codes somewhere safe"
        continueLabel="Done"
        onContinue={() => {
          codesOpen = false;
          newCodes = null;
        }}
      >
        <ol class="codes mono">
          {#each newCodes as code (code)}<li>{code}</li>{/each}
        </ol>
      </SaveSecrets>
    {/if}
  </Dialog>
{/if}

<style>
  .themes {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    margin: 0;
    padding: 0;
    border: 0;
  }
  .themes legend {
    margin-bottom: var(--space-2);
  }
  .end {
    text-align: right;
  }
  .picture {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-4);
  }
  .form-wide {
    max-width: 640px;
  }
  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
    gap: var(--space-4);
  }
  .callout {
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
    max-width: 640px;
    border-left: 4px solid currentColor;
  }
</style>
