"""Commands for the server's console, for what the web UI can't do. The ting
command on the server runs them (deploy/ting); each also runs as

    docker compose exec app python -m app.console <command>

    status              how Þing is: every health check, and the master key's ID
    backup              back up now, and wait for it
    restore-test        restore the newest backup into a scratch folder and check it
    rotate-master-key   replace the master key (with Þing stopped, in the tools
                        service, which may write to /etc/ting)
    reset-allowlist     switch off both IP allowlists, when they lock everyone out
    reset-certificate   go back to Caddy's own certificate authority, when the
                        certificate chosen leaves Þing unreachable
    recovery-code       a new recovery code for the break-glass Administrator, in
                        place of theirs: the way back in when it's lost or may be known

The allowlist addresses stay, so they can be switched on again after fixing them.
Running any of these needs shell access to the server, which is the point.
"""

from __future__ import annotations

import sys
import time
from dataclasses import replace

from sqlalchemy import select
from sqlalchemy.orm import Session

import app.models  # noqa: F401 - run on their own, these load every table
from app import audit, clock, jobs, tls
from app.policy import load_policy, save_policy

STATUS_WORDS = {"ok": "OK", "warning": "Warning", "problem": "Problem", "off": "Off"}


def reset_allowlist(db: Session) -> list[str]:
    """Switch off both allowlists. Returns the ones that were on."""
    policy = load_policy(db)
    were_on = [name for name, on in (("admin panel", policy.admin_allowlist_enabled),
                                     ("sign-in", policy.login_allowlist_enabled)) if on]
    save_policy(db, replace(policy, admin_allowlist_enabled=False, login_allowlist_enabled=False))
    audit.append(db, "admin.allowlist_reset", actor_name="console",
                 details={"switched_off": were_on})
    return were_on


def reset_certificate(db: Session) -> str:
    """Go back to Caddy's own certificate authority. Returns the way it was."""
    before = tls.load_tls(db).mode
    tls.save_tls(db, tls.TlsSettings())
    audit.append(db, "tls.reset", actor_name="console", details={"was": before})
    return before


def status(db: Session) -> int:
    """Print every health check; 1 if any has a problem."""
    from sqlalchemy import text

    from app.maintenance import CHECKS
    from app.settings import settings
    from app.setup import setup_completed_at

    schema = db.execute(text("SELECT version_num FROM alembic_version")).scalar()
    completed = setup_completed_at(db)
    db.commit()
    print(f"Þing at {settings.address}, schema {schema}, "
          f"{'set up ' + completed if completed else 'not set up yet'}.\n")
    problems = 0
    for run in CHECKS.values():
        check = run(db)
        problems += check.status == "problem"
        print(f"  {STATUS_WORDS[check.status]:<8} {check.label:<24} {check.detail}")
    return 1 if problems else 0


def _worker_running(db: Session) -> bool:
    from app.worker import running

    return running(db, clock.utcnow())


def _said(job: jobs.Job) -> str:
    result = job.outcome() or {}
    if job.kind == "backup":
        return (f"backed up {int(result.get('bytes', 0)):,} bytes "
                f"({int(result.get('added', 0)):,} new), snapshot {result.get('snapshot')}")
    return (f"restored snapshot {result.get('snapshot')}: the database and "
            f"{int(result.get('audit_entries', 0)):,} audit log entries check out")


def run_and_wait(db: Session, kind: str, timeout: float = 3 * 3600, poll: float = 2) -> int:
    """Queue a backup or restore test for the worker, one per target (or join one
    already waiting), and wait for them all."""
    from app.backups import load_plan

    names = {"backup": "Backup", "restore_test": "Restore test"}
    plan = load_plan(db)
    if not plan.targets:
        print("Backups are switched off (Admin, Backups).", file=sys.stderr)
        return 1
    if not _worker_running(db):
        print("The worker isn't running, so nothing would do it: start Þing first.",
              file=sys.stderr)
        return 1
    waiting = list(db.scalars(select(jobs.Job).where(
        jobs.Job.kind == kind, jobs.Job.state.in_(("queued", "running")))))
    followed: dict[int, str] = {}
    for target in plan.targets:
        job = next((j for j in waiting
                    if j.data().get("target", plan.targets[0].id) == target.id), None)
        if job is None:
            job = jobs.enqueue(db, kind, {"target": target.id, "via": "console"})
            audit.append(db, f"backup.{kind}_requested", actor_name="console",
                         details={"job": job.id, "target": target.id})
        followed[job.id] = target.words()
    db.commit()
    for job_id, words in followed.items():
        print(f"{names[kind]} {job_id} to {words}: waiting for the worker…", flush=True)
    failures = 0
    deadline = time.monotonic() + timeout
    while followed and time.monotonic() < deadline:
        for job_id, words in list(followed.items()):
            job = db.get(jobs.Job, job_id, populate_existing=True)
            db.commit()
            if job is None:
                del followed[job_id]
            elif job.state == "done":
                print(f"{names[kind]} to {words}: {_said(job)}.", flush=True)
                del followed[job_id]
            elif job.state == "failed" or (job.state == "queued" and job.error):
                retry = "; the worker tries again later" if job.state == "queued" else ""
                print(f"{names[kind]} to {words} failed: {job.error}{retry}", file=sys.stderr)
                failures += 1
                del followed[job_id]
        if followed:
            time.sleep(poll)
    for job_id, words in followed.items():
        print(f"{names[kind]} {job_id} to {words} hasn't finished; it goes on in the worker.",
              file=sys.stderr)
    return 1 if failures or followed else 0


def rotate_master_key() -> int:
    """Finish or undo a rotation left halfway, or replace the master key."""
    from sqlalchemy.orm import Session as _Session

    from app.backups import load_plan
    from app.crypto import rotation
    from app.crypto.keys import to_kit_text
    from app.db import make_engine
    from app.settings import settings

    data_dir, path = settings.data_dir, settings.master_key_path
    try:
        resumed = rotation.resume(data_dir, path)
        if resumed:
            print(f"A rotation that stopped halfway is {resumed} now.")
            if resumed == "finished":
                return 0
        engine = make_engine(data_dir, path)
        try:
            with _Session(engine) as db:
                if _worker_running(db):
                    print("The worker is running: stop Þing first (ting keys rotate does).",
                          file=sys.stderr)
                    return 1
                db.commit()
        finally:
            engine.dispose()
        rotated = rotation.rotate(data_dir, path)
    except PermissionError:
        print(f"{path} can't be written here: run it with ting keys rotate.", file=sys.stderr)
        return 1
    except rotation.RotationError as exc:
        print(f"Not rotated: {exc}", file=sys.stderr)
        return 1
    engine = make_engine(data_dir, path)
    try:
        with _Session(engine) as db:
            keep_days = load_plan(db).keep_days
            db.commit()
    finally:
        engine.dispose()
    print(
        f"The master key is replaced: {rotated.old_id} -> {rotated.new_id}. The database, "
        f"backup and config keys and {rotated.customer_keys} customer "
        f"key{'' if rotated.customer_keys == 1 else 's'} are wrapped with the new one.\n\n"
        "The new master key, for the recovery kit (put it in place of the old one):\n\n"
        f"    {to_kit_text(rotated.new_key)}\n\n"
        f"Keep the old master key ({rotated.old_id}) with the kit until the backups made "
        f"before now have aged out, after {keep_days} days: restoring one of them asks "
        "for it.")
    return 0


def new_break_glass_code(db: Session) -> tuple[str, str] | None:
    """A new recovery code for the break-glass Administrator, in place of theirs.
    Returns their username and the code, or None if there's no such account yet."""
    from app.auth.mfa import issue_recovery_codes
    from app.notices import notify_administrators
    from app.users import User

    user = db.scalars(select(User).where(User.is_break_glass)).first()
    if user is None:
        return None
    (code,) = issue_recovery_codes(db, user.id)
    audit.append(db, "auth.mfa.recovery_codes_issued", actor_name="console",
                 target_type="user", target_id=str(user.id),
                 details={"count": 1, "by": "console", "user": user.username})
    notify_administrators(db, "A new break-glass recovery code was made on the server", (
        f"A new recovery code for the break-glass Administrator ({user.username}) was made "
        "on the server with ting admin recovery-code. The code before it no longer works."))
    return user.username, code


def main(argv: list[str]) -> int:
    from app.db import get_engine

    commands = ("status", "backup", "restore-test", "rotate-master-key", "reset-allowlist",
                "reset-certificate", "recovery-code")
    if len(argv) != 1 or argv[0] not in commands:
        print(__doc__, file=sys.stderr)
        return 2
    command = argv[0]
    if command == "rotate-master-key":
        return rotate_master_key()
    # Nothing reloads after a commit: reading a job while waiting must not start a
    # transaction, which would hold the write lock the worker needs.
    with Session(get_engine(), expire_on_commit=False) as db:
        if command == "status":
            return status(db)
        if command in ("backup", "restore-test"):
            import app.backups  # noqa: F401 - registers the job kinds

            return run_and_wait(db, command.replace("-", "_"))
        if command == "recovery-code":
            made = new_break_glass_code(db)
            db.commit()
            if made is None:
                print("There's no break-glass Administrator yet: the setup wizard makes one.",
                      file=sys.stderr)
                return 1
            username, code = made
            print(f"A new recovery code for the break-glass Administrator, {username}:\n\n"
                  f"    {code}\n\n"
                  "It works every time, in place of the one before, which no longer does. Keep "
                  "it with the recovery kit, never on this server. The Administrators are "
                  "emailed that a new one was made.")
            return 0
        if command == "reset-certificate":
            before = reset_certificate(db)
            db.commit()
            tls.write_for_caddy(tls.TlsSettings())
            print("Þing serves the certificate of its own authority again"
                  f"{'' if before == 'internal' else f' (it was {before})'}; Caddy reloads "
                  "within seconds.")
            return 0
        were_on = reset_allowlist(db)
        db.commit()
        tls.write_admin_allowlist(False, ())
    if were_on:
        print(f"Switched off the {' and '.join(were_on)} allowlist; Þing answers from any "
              "address again.")
    else:
        print("Both allowlists were already off.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
