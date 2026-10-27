"""Backups: encrypted restic snapshots of the data, and a test that they restore.

Every night, at the hour the administrator picks (UTC), the worker copies the
database with SQLite's backup API (the copy is still encrypted with the database
key), puts it beside the wrapped key files and a small manifest, and has restic
back that folder up to each target: this server's backup folder, SMB shares
(through rclone) or S3-compatible storage, one job per target, so one that can't
be reached holds up no other. restic encrypts it all again with the
backup key, as the recovery kit writes it, so a restore needs the kit: the copy
of the backup key in the data folder is itself inside the backup. Snapshots older
than the retention period are forgotten and pruned, and a deleted customer's data
and key age out with them. Once a week the worker restores each target's newest
snapshot into a scratch folder, opens it with the master key, and checks the database's
integrity, the audit chain and the schema version.

Long work runs outside any transaction: a handler reads what it needs, commits,
works, then writes its result.
"""

from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal

import sqlcipher3
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app import audit, clock, jobs
from app.crypto.key_files import load_or_create_backup_key, load_or_create_database_key
from app.crypto.keys import load_master_key
from app.crypto.rotation import key_id, opens
from app.db import check_integrity, make_engine, reading
from app.policy import Setting
from app.sealed_settings import load_secrets
from app.settings import settings

TargetKind = Literal["local", "smb", "s3"]
PLAN_SETTING = "backup/plan"
# Where the one target was kept before there could be several (read once, then moved).
OLD_TARGET_SETTING = "backup/target"
SECRETS = "backup"
LOCAL_REPOSITORY = "/backups/restic"
KEY_FILES = ("db.key.enc", "backup.key.enc", "config.key.enc")
HOST = "ting"
# restic's exit codes for a repository that isn't there, and for a wrong password.
NO_REPOSITORY, WRONG_PASSWORD = 10, 12
LONG = 6 * 60 * 60

_NAME = r"^[A-Za-z0-9._-]*$"
_PATH = r"^[A-Za-z0-9._/-]*$"


class Target(BaseModel):
    """One place backups go. Its secrets are kept apart, sealed, under its ID."""

    id: str = Field(default="local", pattern=r"^[a-z0-9-]{1,40}$")
    kind: TargetKind = "local"
    smb_host: str = Field(default="", max_length=253, pattern=_NAME)
    smb_share: str = Field(default="", max_length=80, pattern=_NAME)
    smb_path: str = Field(default="ting", max_length=200, pattern=_PATH)
    smb_username: str = Field(default="", max_length=100)
    smb_domain: str = Field(default="", max_length=100, pattern=_NAME)
    s3_endpoint: str = Field(default="", max_length=300, pattern=r"^(https?://[^\s/]+/?)?$")
    s3_bucket: str = Field(default="", max_length=63, pattern=_NAME)
    s3_path: str = Field(default="ting", max_length=200, pattern=_PATH)
    s3_region: str = Field(default="", max_length=40, pattern=_NAME)
    s3_access_key_id: str = Field(default="", max_length=200)

    def missing(self) -> str | None:
        """What a target of this kind still needs, in words, or None."""
        if self.kind == "smb" and not (self.smb_host and self.smb_share and self.smb_username):
            return "An SMB share needs its server, share name and user name."
        if self.kind == "s3" and not (
                self.s3_endpoint and self.s3_bucket and self.s3_access_key_id):
            return "S3-compatible storage needs its address, bucket and access key."
        return None

    def words(self) -> str:
        """The target, as a sentence names it."""
        if self.kind == "smb":
            return f"the SMB share \\\\{self.smb_host}\\{self.smb_share}"
        if self.kind == "s3":
            return f"the S3 bucket {self.s3_bucket}"
        return "this server"


class Plan(BaseModel):
    """When backups run, how long they're kept, and where they go: each target gets
    every backup, on its own, so one that can't be reached holds up no other.
    No targets: backups are off."""

    hour: int = Field(default=2, ge=0, le=23)
    keep_days: int = Field(default=90, ge=7, le=3650)
    targets: list[Target] = Field(default_factory=lambda: [Target()], max_length=5)

    def target(self, target_id: str | None) -> Target | None:
        """A target by its ID; the first for a job from before there were several."""
        if target_id is None:
            return self.targets[0] if self.targets else None
        return next((t for t in self.targets if t.id == target_id), None)


class BackupError(Exception):
    """Something went wrong in a way worth saying plainly."""


def load_plan(db: Session) -> Plan:
    stored = db.scalar(select(Setting.value).where(Setting.key == PLAN_SETTING))
    if stored:
        return Plan.model_validate_json(stored)
    # Saved before there could be several targets: one, or "off".
    old = db.scalar(select(Setting.value).where(Setting.key == OLD_TARGET_SETTING))
    if not old:
        return Plan()
    values = json.loads(old)
    kind = values.pop("kind", "local")
    plan = Plan(hour=values.pop("hour", 2), keep_days=values.pop("keep_days", 90), targets=[])
    if kind != "off":
        plan.targets.append(Target.model_validate(values | {"id": kind, "kind": kind}))
    return plan


def save_plan(db: Session, plan: Plan) -> None:
    db.merge(Setting(key=PLAN_SETTING, value=plan.model_dump_json()))


def load_target_secrets(db: Session, plan: Plan) -> dict[str, dict[str, str]]:
    """Each target's secrets by its ID. Secrets saved before there could be several
    targets belong to the first."""
    stored = load_secrets(db, SECRETS)
    flat = {k: v for k, v in stored.items() if isinstance(v, str)}
    secrets = {k: dict(v) for k, v in stored.items() if isinstance(v, dict)}
    if flat and plan.targets:
        secrets.setdefault(plan.targets[0].id, {}).update(flat)
    return secrets


def repository(target: Target) -> str:
    """The restic repository a target means."""
    if target.kind == "smb":
        return f"rclone:tingsmb:{target.smb_share}/{target.smb_path.strip('/')}"
    if target.kind == "s3":
        return (f"s3:{target.s3_endpoint.rstrip('/')}/{target.s3_bucket}/"
                f"{target.s3_path.strip('/')}")
    return LOCAL_REPOSITORY


def password(backup_key: bytes) -> str:
    """The repository password: the backup key as the recovery kit writes it,
    without the spaces."""
    return base64.b32encode(backup_key).decode().rstrip("=")


def _obscure(secret: str) -> str:
    """rclone wants passwords obscured; read from stdin, so it's never an argument."""
    done = subprocess.run(["rclone", "obscure", "-"], input=secret, capture_output=True,
                          text=True, timeout=30, check=False)
    if done.returncode != 0:
        raise BackupError("rclone couldn't prepare the SMB password.")
    return done.stdout.strip()


def environment(target: Target, secrets: dict[str, Any], key_text: str) -> dict[str, str]:
    """What restic (and rclone) need, passed as environment, never as arguments."""
    env = {
        "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
        "HOME": "/tmp",
        "RESTIC_REPOSITORY": repository(target),
        "RESTIC_PASSWORD": key_text,
        "RESTIC_CACHE_DIR": "/tmp/restic-cache",
    }
    if target.kind == "s3":
        env |= {
            "AWS_ACCESS_KEY_ID": target.s3_access_key_id,
            "AWS_SECRET_ACCESS_KEY": str(secrets.get("s3_secret_access_key", "")),
            "AWS_DEFAULT_REGION": target.s3_region or "us-east-1",
        }
    if target.kind == "smb":
        prefix = "RCLONE_CONFIG_TINGSMB_"
        env |= {
            prefix + "TYPE": "smb",
            prefix + "HOST": target.smb_host,
            prefix + "USER": target.smb_username,
            prefix + "PASS": _obscure(str(secrets.get("smb_password", ""))),
            prefix + "DOMAIN": target.smb_domain or "WORKGROUP",
        }
    return env


def _explain(code: int, stderr: str) -> str:
    """restic's complaint in plain words, as far as it can be put so."""
    said = stderr.lower()
    if code == WRONG_PASSWORD or "wrong password" in said:
        return ("The backup key doesn't open the repository there: it was made with another "
                "key. Point backups somewhere empty, or restore with the key that made it.")
    if any(s in said for s in ("no such host", "connection refused", "timeout", "unreachable",
                               "couldn't connect", "no route")):
        return "The backup target can't be reached."
    if any(s in said for s in ("access denied", "403", "permission denied", "logon failure",
                               "invalidaccesskeyid", "signaturedoesnotmatch")):
        return "The backup target refused the user name, password or key."
    lines = [line for line in stderr.strip().splitlines() if line.strip()]
    return (lines[-1] if lines else f"restic stopped with code {code}.")[:300]


def restic(env: dict[str, str], *args: str, timeout: int = LONG) -> str:
    done = subprocess.run(["restic", *args], env=env, capture_output=True, text=True,
                          timeout=timeout, check=False)
    if done.returncode != 0:
        raise BackupError(_explain(done.returncode, done.stderr))
    return done.stdout


def ensure_repository(env: dict[str, str]) -> bool:
    """Make the repository if there's none yet. Returns whether it was made."""
    done = subprocess.run(["restic", "cat", "config"], env=env, capture_output=True,
                          text=True, timeout=300, check=False)
    if done.returncode == 0:
        return False
    if done.returncode == NO_REPOSITORY:
        restic(env, "init")
        return True
    raise BackupError(_explain(done.returncode, done.stderr))


def _summary(output: str) -> dict[str, Any]:
    for line in reversed(output.strip().splitlines()):
        message = json.loads(line)
        if message.get("message_type") == "summary":
            summary: dict[str, Any] = message
            return summary
    raise BackupError("restic finished without saying what it backed up.")


def _stage(folder: Path, manifest: dict[str, Any]) -> None:
    """A consistent copy of the data to back up: the database, through SQLite's
    backup API (still encrypted with the database key), the wrapped key files
    and a manifest."""
    data_dir = Path(settings.data_dir)
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(mode=0o700, parents=True)
    database_key = load_or_create_database_key(data_dir, settings.master_key_path)
    key = f"PRAGMA key = \"x'{database_key.hex()}'\""
    source = sqlcipher3.connect(str(data_dir / "ting.db"))
    copy = sqlcipher3.connect(str(folder / "ting.db"))
    try:
        source.execute(key)
        copy.execute(key)
        source.backup(copy)
    finally:
        copy.close()
        source.close()
    for name in KEY_FILES:
        if (data_dir / name).exists():
            shutil.copy2(data_dir / name, folder / name)
    (folder / "manifest.json").write_text(json.dumps(manifest, indent=2))


def _tell(db: Session, subject: str, body: str) -> None:
    """An email to the Administrators, if email is set up."""
    from app.notices import notify_administrators

    notify_administrators(db, subject, body)
    db.commit()


def _log(db: Session, action: str, job: jobs.Job, details: dict[str, Any]) -> None:
    audit.append(db, action, actor_id=job.requested_by, target_type="job",
                 target_id=str(job.id), details=details)
    db.commit()


def _prepare(db: Session, job: jobs.Job) -> tuple[Target, dict[str, str]]:
    """The job's target and restic's environment, read before the long work begins."""
    plan = load_plan(db)
    target = plan.target(job.data().get("target"))
    if target is None:
        raise BackupError("That backup target isn't there any more." if plan.targets
                          else "Backups are switched off.")
    if target.missing():
        raise BackupError(target.missing() or "")
    key_text = password(load_or_create_backup_key(settings.data_dir, settings.master_key_path))
    secrets = load_target_secrets(db, plan).get(target.id, {})
    return target, environment(target, secrets, key_text)


def latest(db: Session, kind: str, target: Target, first: bool, *states: str) -> jobs.Job | None:
    """The newest job of a kind for one target (a job from before there were several
    targets counts as the first's)."""
    for job in db.scalars(select(jobs.Job).where(jobs.Job.kind == kind,
                                                 jobs.Job.state.in_(states))
                          .order_by(jobs.Job.finished_at.desc(), jobs.Job.id.desc()).limit(200)):
        named = job.data().get("target")
        if named == target.id or (named is None and first):
            return job
    return None


@jobs.handles("backup")
def run_backup(db: Session, job: jobs.Job) -> dict[str, Any]:
    target, env = _prepare(db, job)
    keep_days = load_plan(db).keep_days
    head = db.scalar(select(audit.AuditEntry.seq).order_by(audit.AuditEntry.seq.desc()).limit(1))
    manifest = {
        "made_at": clock.utcnow().isoformat(),
        "schema": db.execute(text("SELECT version_num FROM alembic_version")).scalar(),
        "audit_entries": head or 0,
        # Restoring needs this master key (the kit's, or an older one after a rotation).
        "master_key_id": key_id(load_master_key(settings.master_key_path)),
    }
    db.commit()  # long work follows: hold no lock meanwhile
    folder = Path(settings.data_dir) / f".backup-{job.id}"
    try:
        _stage(folder, manifest)
        created = ensure_repository(env)
        summary = _summary(restic(env, "backup", "--json", "--host", HOST, "--tag", HOST,
                                  str(folder)))
        restic(env, "forget", "--host", HOST, "--keep-within-daily",
               f"{keep_days}d", "--prune")
    except (BackupError, OSError, subprocess.SubprocessError, sqlcipher3.Error) as exc:
        _log(db, "backup.failed", job, {"target": target.id, "error": str(exc)[:300]})
        if job.attempts >= jobs.MAX_ATTEMPTS:
            _tell(db, "Þing couldn't back up", (
                f"The backup to {target.words()} failed {job.attempts} times in a "
                f"row; the last time: {exc}\n\nAdmin, Backups has the details."))
        raise
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    result = {
        "snapshot": str(summary.get("snapshot_id", ""))[:8],
        "files": summary.get("total_files_processed", 0),
        "bytes": summary.get("total_bytes_processed", 0),
        "added": summary.get("data_added", 0),
        "target": target.id,
        "repository_made": created,
    }
    _log(db, "backup.completed", job, result)
    return result


def check_restored(folder: Path) -> dict[str, Any]:
    """Open a restored copy with the master key and check it end to end."""
    manifest = json.loads((folder / "manifest.json").read_text())
    current = load_master_key(settings.master_key_path)
    if not opens(folder, current):
        made_under = manifest.get("master_key_id") or "an earlier one"
        raise BackupError(
            f"It was made under master key {made_under}, before the master key was rotated "
            f"(this server's is {key_id(current)}). ting restore asks for that key; the "
            "next backup is made under this one.")
    engine = make_engine(folder, settings.master_key_path)
    try:
        problems = check_integrity(engine)
        with reading(engine) as restored:
            chain = audit.verify(restored)
            schema = restored.execute(text("SELECT version_num FROM alembic_version")).scalar()
    except (DBAPIError, sqlcipher3.Error) as exc:
        # Damage can stop SQLite reading the copy at all, before the check runs.
        raise BackupError("The restored database failed its integrity check: it can't be "
                          "read.") from exc
    finally:
        engine.dispose()
    if problems:
        raise BackupError("The restored database failed its integrity check.")
    if not chain.ok:
        raise BackupError(f"The restored audit log breaks at entry {chain.first_bad_seq}.")
    if schema != manifest.get("schema") or chain.entries_checked < manifest["audit_entries"]:
        raise BackupError("The restored copy doesn't match what was backed up.")
    return {"schema": schema, "audit_entries": chain.entries_checked,
            "made_at": manifest.get("made_at")}


@jobs.handles("restore_test")
def run_restore_test(db: Session, job: jobs.Job) -> dict[str, Any]:
    target, env = _prepare(db, job)
    db.commit()
    scratch = Path(settings.data_dir) / f".restore-test-{job.id}"
    shutil.rmtree(scratch, ignore_errors=True)
    try:
        newest = json.loads(restic(env, "snapshots", "latest", "--host", HOST, "--json"))
        if not newest:
            raise BackupError("There's no backup to test yet.")
        restic(env, "check")
        restic(env, "restore", "latest", "--host", HOST, "--target", str(scratch))
        found = next(scratch.rglob("manifest.json"), None)
        if found is None:
            raise BackupError("The newest backup has no manifest; it isn't Þing's.")
        result = check_restored(found.parent) | {
            "snapshot": str(newest[-1].get("short_id", ""))[:8], "target": target.id}
    except (BackupError, OSError, subprocess.SubprocessError, ValueError) as exc:
        _log(db, "backup.restore_test_failed", job, {"target": target.id,
                                                      "error": str(exc)[:300]})
        if job.attempts >= jobs.MAX_ATTEMPTS:
            _tell(db, "Þing's restore test failed", (
                f"Restoring the newest backup from {target.words()} failed "
                f"{job.attempts} times in a row; the last time: {exc}\n\n"
                "Until it passes, don't count on that backup. Admin, Backups has the details."))
        raise
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    _log(db, "backup.restore_tested", job, result)
    _tell(db, "Þing's restore test passed", (
        f"The newest backup ({result['snapshot']}, made {str(result.get('made_at'))[:16]}Z) was "
        f"restored from {target.words()} into a scratch folder and checked: the "
        f"database, and {result['audit_entries']:,} audit log entries in an unbroken chain."))
    return result


@jobs.handles("backup_check")
def check_target(db: Session, job: jobs.Job) -> dict[str, Any]:
    """Reach the target, making the repository if it's new, and count its snapshots."""
    target, env = _prepare(db, job)
    db.commit()
    created = ensure_repository(env)
    snapshots = json.loads(restic(env, "snapshots", "--json", timeout=300)) or []
    return {"target": target.id, "repository_made": created, "snapshots": len(snapshots)}


def next_backup(plan: Plan, done_today: bool, now: datetime) -> datetime | None:
    """When the next nightly backup is due: tonight's hour, tomorrow's once today's is
    done, or now when today's hour has passed without one (the worker catches up)."""
    if not plan.targets:
        return None
    today = now.replace(hour=plan.hour, minute=0, second=0, microsecond=0)
    if done_today:
        return today + timedelta(days=1)
    return max(today, now)


@jobs.scheduled
def _nightly(db: Session, now: datetime) -> list[tuple[str, str, dict[str, Any]]]:
    plan = load_plan(db)
    if now.hour < plan.hour:
        return []
    return [("backup", f"backup/{now.date().isoformat()}/{target.id}", {"target": target.id})
            for target in plan.targets if not target.missing()]


@jobs.scheduled
def _weekly_restore_test(db: Session, now: datetime) -> list[tuple[str, str, dict[str, Any]]]:
    plan = load_plan(db)
    year, week, _ = now.isocalendar()
    return [("restore_test", f"restore_test/{year}-W{week:02d}/{target.id}",
             {"target": target.id})
            for index, target in enumerate(plan.targets)
            if latest(db, "backup", target, index == 0, "done") is not None]
