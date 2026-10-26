<script lang="ts">
  import { resolve } from "$app/paths";
  import { page } from "$app/state";
  import { onMount } from "svelte";
  import { api, ApiError } from "#lib/api.js";
  import {
    PROFILE_FIELDS,
    profileForm,
    userStatus,
    type ProfileForm,
    type UserDetail,
  } from "#lib/admin.js";
  import { pageTitle } from "#lib/branding.svelte.js";
  import Avatar from "#lib/components/Avatar.svelte";
  import Pill from "#lib/components/Pill.svelte";
  import UserActions, { type UserAction } from "#lib/components/UserActions.svelte";
  import { browserName, date, dateTime } from "#lib/format.js";
  import { ROLES, type Role } from "#lib/roles.js";
  import { session } from "#lib/session.svelte.js";
  import { toast } from "#lib/toast.svelte.js";

  const KIND_NAMES = { totp: "Authenticator app", webauthn: "Passkey or security key" };

  let user = $state<UserDetail | null>(null);
  let form = $state<ProfileForm | null>(null);
  let roles = $state<Role[]>([]);
  let error = $state<string | null>(null);
  let busy = $state(false);
  let actions: UserActions;

  const id = $derived(page.params.id);
  const isSelf = $derived(user?.id === session.current?.user.id);
  const status = $derived(user ? userStatus(user) : null);

  function use(detail: UserDetail) {
    user = detail;
    form = profileForm(detail);
    roles = [...detail.roles];
  }

  onMount(async () => {
    try {
      use(await api<UserDetail>("GET", `/admin/users/${id}`));
    } catch (e) {
      error = e instanceof ApiError ? e.message : "Not found.";
    }
  });

  async function run(action: () => Promise<void>) {
    busy = true;
    error = null;
    try {
      await action();
    } catch (e) {
      error = e instanceof ApiError ? e.message : "Something went wrong. Try again.";
    } finally {
      busy = false;
    }
  }

  function save(event: SubmitEvent) {
    event.preventDefault();
    run(async () => {
      use(await api<UserDetail>("PATCH", `/admin/users/${id}`, { ...form, roles }));
      toast("Saved.", "ok", { key: "saved" });
    });
  }

  function start(action: UserAction) {
    if (user) actions.start(action, user);
  }

  function endSession(sessionId: number) {
    run(async () => {
      use(await api<UserDetail>("POST", `/admin/users/${id}/sessions/${sessionId}/end`));
      toast("That session has ended. They're told why when their browser checks in.", "ok");
    });
  }
</script>

<svelte:head><title>{pageTitle(`${user?.display_name ?? "User"} · Admin`)}</title></svelte:head>

<div class="page-header">
  <div>
    <a class="small" href={resolve("/(app)/admin/users")}>Users</a>
    <div class="who">
      {#if user}<Avatar name={user.display_name} url={user.avatar_url} size={48} />{/if}
      <div>
        <h1 class="title">{user?.display_name ?? "User"}</h1>
        {#if user && status}
          <div class="tags">
            <span class="small muted mono">{user.username}</span>
            <Pill tone={status.tone} text={status.text} />
            {#if user.is_break_glass}<Pill tone="info" text="Break-glass" />{/if}
          </div>
        {/if}
      </div>
    </div>
  </div>
</div>

{#if error}<p class="alert alert-critical" role="alert">{error}</p>{/if}

{#if user && form}
  {#if user.is_break_glass}
    <p class="alert alert-warning">
      The break-glass administrator is for setup and emergencies. It always keeps the
      Administrator role, stays active and needs multifactor, and every sign-in with it is
      flagged in the audit log.
    </p>
  {/if}

  <form class="section stack" onsubmit={save}>
    <h2 class="section-title">Profile and roles</h2>
    <p class="small muted">
      Work details reports can use, and the roles that decide what they can do. Roles add up: each
      one gives its own rights, and nobody gets more by holding a "higher" one.
    </p>
    <div class="columns">
      <div class="stack">
        <div class="field">
          <label for="display-name">Display name</label>
          <input id="display-name" class="input" required maxlength="200"
            bind:value={form.display_name} />
          <span class="hint">How Þing shows them, such as “Bjørn Havn”.</span>
        </div>
        <div class="grid">
          {#each PROFILE_FIELDS as field (field.key)}
            <div class="field">
              <label for={field.key}>{field.label}</label>
              <input id={field.key} class="input" type={field.type ?? "text"}
                autocomplete="off" bind:value={form[field.key]} />
            </div>
          {/each}
        </div>
      </div>
      <fieldset class="checks roles">
        <legend class="check-title">Roles</legend>
        {#each ROLES as option (option.role)}
          <label class="check">
            <input type="checkbox" value={option.role} bind:group={roles}
              disabled={option.role === "administrator" && (isSelf || user.is_break_glass)} />
            <span>
              <span class="check-title">{option.name}</span>
              <span class="small muted">{option.description}</span>
            </span>
          </label>
        {/each}
      </fieldset>
    </div>
    <div><button class="button button-primary" type="submit" disabled={busy}>Save changes</button></div>
  </form>

  <section class="section">
    <h2 class="section-title">Sign-in</h2>
    <p class="small muted">
      How they sign in, and what to do when they're stuck: a forgotten password, a lost phone or
      key, or a locked account. Each action ends their sessions where it makes sense.
    </p>
    <dl class="facts">
      <dt>Account</dt>
      <dd>{user.is_active ? "Active" : "Disabled: can't sign in"}</dd>
      <dt>Last sign-in</dt>
      <dd>{dateTime(user.last_sign_in_at)}</dd>
      <dt>Password</dt>
      <dd>
        {#if user.password_change_required}
          To be changed at first sign-in; works until {dateTime(user.password_expires_at)}
        {:else}
          Their own
        {/if}
      </dd>
      <dt>Multifactor</dt>
      <dd>{user.mfa_required ? "Required" : "Not required"}</dd>
      <dt>Recovery codes</dt>
      <dd>{user.recovery_codes_left} of 10 left</dd>
      <dt>Lockout</dt>
      <dd>{user.locked ? "Locked after too many wrong attempts" : "Not locked"}</dd>
    </dl>

    <h3 class="check-title">Multifactor methods</h3>
    {#if user.factors.length}
      <ul class="plain">
        {#each user.factors as factor (factor.id)}
          <li>
            {factor.label}
            <span class="muted">
              {factor.label === KIND_NAMES[factor.kind] ? "" : `· ${KIND_NAMES[factor.kind]} `}·
              added {date(factor.created_at)} · last used {dateTime(factor.last_used_at)}
            </span>
          </li>
        {/each}
      </ul>
    {:else}
      <p class="muted">
        None set up{user.mfa_required ? " yet. They set one up at their next sign-in." : "."}
      </p>
    {/if}

    {#if isSelf}
      <p class="small muted">
        For your own password, multifactor and sessions, use
        <a href={resolve("/(app)/account")}>Your account</a>.
      </p>
    {:else}
      <div class="button-row">
        <button class="button button-secondary" type="button" disabled={busy}
          onclick={() => start("reset-password")}>Reset password</button>
        <button class="button button-secondary" type="button" disabled={busy || !user.factors.length}
          onclick={() => start("reset-mfa")}>Reset multifactor</button>
        <button class="button button-secondary" type="button" disabled={busy || !user.sessions.length}
          onclick={() => start("sign-out")}>Sign out everywhere</button>
        {#if user.locked}
          <button class="button button-secondary" type="button" disabled={busy}
            onclick={() => start("unlock")}>Unlock</button>
        {/if}
        {#if !user.is_break_glass}
          {#if user.is_active}
            <button class="button button-secondary danger" type="button" disabled={busy}
              onclick={() => start("disable")}>Disable account</button>
          {:else}
            <button class="button button-secondary" type="button" disabled={busy}
              onclick={() => start("enable")}>Enable account</button>
          {/if}
        {/if}
      </div>
    {/if}
  </section>

  <section class="section">
    <h2 class="section-title">Sessions</h2>
    <p class="small muted">
      Browsers signed in to this account. Ending one signs that browser out at once; it's told
      an administrator did it.
    </p>
    {#if user.sessions.length}
      <div class="table-wrap">
        <table class="table">
          <thead>
            <tr>
              <th>Browser</th><th>Address</th><th>Signed in</th><th>Last active</th>
              <th>Multifactor</th><th><span class="visually-hidden">Actions</span></th>
            </tr>
          </thead>
          <tbody>
            {#each user.sessions as row (row.id)}
              <tr>
                <td>{browserName(row.user_agent)}</td>
                <td class="mono">{row.ip ?? "—"}</td>
                <td>{dateTime(row.created_at)}</td>
                <td>{dateTime(row.last_seen_at)}</td>
                <td>{row.second_factor_done ? "Passed" : "Not yet"}</td>
                <td class="end">
                  {#if !isSelf}
                    <button class="link-button" type="button" disabled={busy}
                      onclick={() => endSession(row.id)}>
                      End session<span class="visually-hidden">: {browserName(row.user_agent)},
                        signed in {dateTime(row.created_at)}</span>
                    </button>
                  {/if}
                </td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    {:else}
      <p class="muted">Not signed in anywhere.</p>
    {/if}
  </section>
{/if}

<UserActions bind:this={actions} onChanged={use} />

<style>
  .who {
    display: flex;
    align-items: center;
    gap: var(--space-4);
    margin-top: var(--space-1);
  }
  .tags {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-2);
    margin-top: var(--space-1);
  }
  .columns {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
    gap: var(--space-6);
  }
  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
    gap: var(--space-4);
  }
  .roles {
    margin: 0;
    padding: 0;
    border: 0;
  }
  .roles legend {
    margin-bottom: var(--space-2);
  }
  .plain {
    margin: 0;
    padding-left: 1.2em;
  }
  .end {
    text-align: right;
  }
  .danger {
    border-color: var(--critical-text);
    color: var(--critical-text);
  }
</style>
