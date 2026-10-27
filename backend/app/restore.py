"""Restore a backup: `python -m app.restore`, with Þing stopped. `ting restore`
on the server stops Þing, runs it in a worker container, and starts it again.

It asks for the backup key from the recovery kit, restores the snapshot (the
newest unless --snapshot says otherwise) into a scratch folder and checks it as
the weekly restore test does. Only then does it move the current data aside, into
a folder named for the time (nothing is deleted), and put the restored copy in
its place. On a new server, put the recovery kit's master key in
/etc/ting/master.key first (the installer does it with --restore-master-key).
A backup made before the master key was rotated asks for the master key it was
made under, and the restored copy is moved to the server's current one.

The target comes from Þing's own settings when the database still opens;
otherwise give --repository (such as /backups/restic, or an s3: or rclone:
address), with the credentials restic and rclone read from the environment
(AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, RCLONE_CONFIG_TINGSMB_...).
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import shutil
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import sqlcipher3
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

import app.models  # noqa: F401 - run on their own, these load every table
from app import audit, clock
from app.auth.mfa import RecoveryCode
from app.backups import (
    HOST,
    KEY_FILES,
    BackupError,
    check_restored,
    environment,
    load_plan,
    load_target_secrets,
    password,
    restic,
)
from app.crypto.keys import from_kit_text, load_master_key
from app.crypto.rotation import key_id, opens, rewrap_restored
from app.db import make_engine
from app.jobs import Job
from app.settings import settings
from app.users import User

DATA_FILES = ("ting.db", "ting.db-wal", "ting.db-shm", *KEY_FILES)


def _settle_jobs(folder: Path) -> None:
    """Jobs the copy shows running were running when the backup was made (the backup
    itself, at least). Nothing runs them after a restore, so they're marked failed:
    left running, they'd look busy forever and keep the same job from being asked
    for again."""
    engine = make_engine(folder, settings.master_key_path)
    try:
        with Session(engine) as db:
            for job in db.scalars(select(Job).where(Job.state == "running")):
                job.state, job.finished_at = "failed", clock.utcnow()
                job.error = "It was running when the backup was made; the restore ended it."
            db.commit()
    finally:
        engine.dispose()


def _carry_recovery_codes(restored: Path, data_dir: Path) -> dict[str, Any]:
    """Recovery codes as they are now, not as they were at the backup: a code used
    since would work again, and someone who made new codes since would get the old
    ones back. Carried over for everyone in both, matched by ID and username, from
    the data being replaced; when that can't be read, say what that means."""
    current = load_master_key(settings.master_key_path)
    if not (data_dir / "ting.db").exists() or not opens(data_dir, current):
        return {"recovery_codes": "as_backed_up"}
    try:
        engine = make_engine(data_dir, settings.master_key_path)
        try:
            with Session(engine) as now:
                people = {u.id: u.username for u in now.scalars(select(User))}
                codes = list(now.scalars(select(RecoveryCode)))
                now.expunge_all()
        finally:
            engine.dispose()
    except (DBAPIError, sqlcipher3.Error):
        return {"recovery_codes": "as_backed_up"}
    engine = make_engine(restored, settings.master_key_path)
    try:
        with Session(engine) as db:
            carried = 0
            for user in db.scalars(select(User)):
                if people.get(user.id) != user.username:
                    continue
                theirs = [c for c in codes if c.user_id == user.id]
                then = list(db.scalars(select(RecoveryCode).where(RecoveryCode.user_id == user.id)))
                if sorted((c.code_hash, c.used_at) for c in then) == sorted(
                        (c.code_hash, c.used_at) for c in theirs):
                    continue
                for code in then:
                    db.delete(code)
                for code in theirs:
                    db.add(RecoveryCode(user_id=code.user_id, salt=code.salt,
                                        code_hash=code.code_hash, created_at=code.created_at,
                                        used_at=code.used_at))
                carried += 1
            db.commit()
    finally:
        engine.dispose()
    return {"recovery_codes": "carried_over", "recovery_codes_changed_for": carried}


def _record(restored: Path, snapshot: str, found: dict[str, Any]) -> None:
    """The restore, in the restored audit log, and to the Administrators by email (the
    worker sends it once Þing runs again)."""
    from app.notices import notify_administrators

    codes = ("Recovery codes are as they were just before the restore: used ones stay "
             "used." if found["recovery_codes"] == "carried_over" else
             "Recovery codes are as they were at the backup: any used since work again, "
             "so people who used one should make new ones under Your account.")
    engine = make_engine(restored, settings.master_key_path)
    try:
        with Session(engine) as db:
            audit.append(db, "backup.restored", actor_name="console", details={
                "snapshot": snapshot, "made_at": found.get("made_at"),
                "recovery_codes": found["recovery_codes"]})
            notify_administrators(db, "Þing was restored from a backup", (
                f"Þing was restored on the server from the backup made "
                f"{str(found.get('made_at'))[:16]}Z (snapshot {snapshot}). Everything done "
                f"since that backup is gone from Þing; the data from before the restore "
                f"is kept on the server.\n\n{codes} Passwords and second factors are as they "
                "were at the backup."))
            db.commit()
    finally:
        engine.dispose()


# Asked for the master key a backup was made under (named by its ID, if the backup
# says), when it isn't the server's own.
OlderKey = Callable[[str | None], bytes]


def restore(env: dict[str, str], snapshot: str, data_dir: Path,
            older_key: OlderKey | None = None) -> dict[str, Any]:
    """Restore a snapshot into data_dir, keeping what was there in a folder beside it.
    Returns what the check found, and where the old data went."""
    scratch = data_dir / ".restore"
    shutil.rmtree(scratch, ignore_errors=True)
    try:
        restic(env, "restore", snapshot, "--host", HOST, "--target", str(scratch))
        manifest = next(scratch.rglob("manifest.json"), None)
        if manifest is None:
            raise BackupError("That snapshot has no manifest; it isn't Þing's.")
        restored = manifest.parent
        made_under = json.loads(manifest.read_text()).get("master_key_id")
        if older_key is not None and not opens(restored, load_master_key(settings.master_key_path)):
            old = older_key(made_under)
            if not opens(restored, old):
                raise BackupError("That master key doesn't open this backup either.")
            rewrap_restored(restored, old, settings.master_key_path)
        found = check_restored(restored)
        _settle_jobs(restored)
        found |= _carry_recovery_codes(restored, data_dir)
        snapshot_id = _snapshot_id(env, snapshot)
        _record(restored, snapshot_id, found)
        found["snapshot"] = snapshot_id
        kept = data_dir / f".before-restore-{clock.utcnow().strftime('%Y%m%dT%H%M%SZ')}"
        kept.mkdir(mode=0o700)
        for name in DATA_FILES:
            if (data_dir / name).exists():
                (data_dir / name).rename(kept / name)
        for name in ("ting.db", *KEY_FILES):
            if (restored / name).exists():
                (restored / name).rename(data_dir / name)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    return found | {"kept": str(kept)}


def _snapshot_id(env: dict[str, str], snapshot: str) -> str:
    """The snapshot's short ID ("latest" names no particular one)."""
    try:
        listed = json.loads(restic(env, "snapshots", snapshot, "--host", HOST, "--json"))
        return str(listed[-1].get("short_id", snapshot)) if listed else snapshot
    except (BackupError, ValueError):
        return snapshot


def _target_environment(key_text: str, repository: str | None,
                        target_id: str | None) -> dict[str, str]:
    """restic's environment: from a saved target (the first, unless --target names
    another), or from --repository and the credentials already in this process's
    environment."""
    if repository:
        return {**os.environ, "RESTIC_REPOSITORY": repository, "RESTIC_PASSWORD": key_text,
                "RESTIC_CACHE_DIR": "/tmp/restic-cache", "HOME": "/tmp"}
    engine = make_engine()
    try:
        with Session(engine) as db:
            plan = load_plan(db)
            target = plan.target(target_id)
            if target is None:
                raise BackupError(f"There's no backup target {target_id}: the targets are "
                                  f"{', '.join(t.id for t in plan.targets) or 'none'}.")
            secrets = load_target_secrets(db, plan).get(target.id, {})
            return environment(target, secrets, key_text)
    finally:
        engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Restore Þing from a backup.")
    parser.add_argument("--snapshot", default="latest", help="snapshot ID (default: latest)")
    parser.add_argument("--target", help="which backup target to restore from (default: the "
                                          "first one in Admin, Backups)")
    parser.add_argument("--repository", help="restic repository, if Þing's settings are gone")
    parser.add_argument("--yes", action="store_true", help="don't ask before replacing data")
    args = parser.parse_args(argv)

    kit = getpass.getpass("Backup key, from the recovery kit: ")
    try:
        key_text = password(from_kit_text(kit))
    except ValueError:
        print("That isn't a backup key as the recovery kit writes it.", file=sys.stderr)
        return 2
    try:
        env = _target_environment(key_text, args.repository, args.target)
    except BackupError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001 - the database may be the thing that's lost
        print(f"Þing's settings can't be read ({exc}); give --repository.", file=sys.stderr)
        return 2
    data_dir = Path(settings.data_dir)
    if not args.yes:
        print(f"This replaces the data in {data_dir} with snapshot {args.snapshot!r} from "
              f"{env['RESTIC_REPOSITORY']}. The current data is kept beside it. Þing must "
              "be stopped.")
        if input("Type restore to go on: ").strip() != "restore":
            print("Nothing changed.")
            return 1
    current = key_id(load_master_key(settings.master_key_path))

    def ask(made_under: str | None) -> bytes:
        print(f"This backup was made under master key {made_under or 'an earlier one'}, "
              f"not this server's ({current}): the master key was rotated since.", flush=True)
        text = getpass.getpass("That master key, from the recovery kit kept then: ")
        try:
            return from_kit_text(text)
        except ValueError as exc:
            raise BackupError("That isn't a master key as the recovery kit writes it.") from exc

    try:
        found = restore(env, args.snapshot, data_dir, older_key=ask)
    except BackupError as exc:
        print(f"Not restored: {exc}", file=sys.stderr)
        return 1
    print(f"Restored snapshot {found['snapshot']}: schema {found['schema']}, "
          f"{found['audit_entries']:,} audit log entries, backed up {found['made_at']}. The "
          f"data that was there is in {found['kept']}.")
    if found["recovery_codes"] == "carried_over":
        changed = found["recovery_codes_changed_for"]
        print("Recovery codes are as they were just before the restore, not at the backup: "
              f"used ones stay used ({changed} {'person' if changed == 1 else 'people'} "
              "had used or replaced codes since the backup).")
    else:
        print("Recovery codes are as they were at the backup (the data before couldn't be "
              "read): any code used since works again. Ask people who used one to make new "
              "ones under Your account.")
    print("Passwords and second factors are as they were at the backup. The restore is in "
          "the audit log, and the Administrators are emailed when Þing runs again.")
    if not os.environ.get("TING_COMMAND"):  # ting restore starts it again itself
        print("Start Þing again with: ting start (or docker compose up -d)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
