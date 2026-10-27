"""Server health for Administrators: checks, space used, software versions.

Each check is its own request, so the page fills in as they finish. The slow
ones (the database's integrity check, re-hashing the audit chain, the call to
Have I Been Pwned) run outside any write transaction, so the rest of Þing
carries on meanwhile.
"""

from __future__ import annotations

import importlib.metadata
import platform
import shutil
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app import audit, audit_stamps, clock, worker
from app.admin import Admin
from app.audit import AuditEntry
from app.auth import pwned
from app.auth.dependencies import DB
from app.auth.sessions import UserSession
from app.backups import Plan, latest, load_plan
from app.crypto.keys import load_master_key
from app.crypto.rotation import key_id
from app.db import check_integrity, engine_of, reading
from app.images import StoredImage
from app.jobs import Job
from app.policy import load_policy
from app.settings import settings
from app.setup import setup_completed_at
from app.users import User
from app.version import ting_version

router = APIRouter(prefix="/admin")

STARTED_AT = clock.utcnow()
GIB = 1024**3
# Free space below either limit is a warning; below both halves of it, a problem.
LOW_DISK_FRACTION = 0.15
LOW_DISK_BYTES = 2 * GIB

Status = Literal["ok", "warning", "problem", "off"]


class Check(BaseModel):
    key: str
    label: str
    status: Status
    detail: str


class Usage(BaseModel):
    disk_total_bytes: int
    disk_free_bytes: int
    database_bytes: int
    images_bytes: int
    audit_entries: int
    users: int
    active_users: int
    sessions: int


class Versions(BaseModel):
    ting: str
    python: str
    sqlite: str
    sqlcipher: str
    schema_version: str | None
    operating_system: str
    kernel: str


class Package(BaseModel):
    name: str
    version: str


class ServerHealth(BaseModel):
    checked_at: datetime
    started_at: datetime
    address: str
    setup_completed_at: str | None
    # The keys of the checks to run, one request each (see run_check).
    checks: list[str]
    usage: Usage
    versions: Versions
    packages: list[Package]


def _operating_system() -> str:
    try:
        for line in Path("/etc/os-release").read_text().splitlines():
            if line.startswith("PRETTY_NAME="):
                return line.partition("=")[2].strip().strip('"')
    except OSError:
        pass
    return platform.system()


def _packages() -> list[Package]:
    found = {
        dist.metadata["Name"].lower(): dist.version
        for dist in importlib.metadata.distributions()
        if dist.metadata["Name"]
    }
    return [Package(name=name, version=version) for name, version in sorted(found.items())]


def _file_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _database_check(problems: list[str]) -> Check:
    if not problems:
        return Check(key="database", label="Database", status="ok",
                     detail="Encrypted, and every page passed the integrity check.")
    return Check(key="database", label="Database", status="problem",
                 detail="The integrity check found problems: " + "; ".join(problems[:3]))


def _audit_check(result: audit.ChainCheck) -> Check:
    if result.ok:
        return Check(key="audit_chain", label="Audit log", status="ok",
                     detail=f"Chain intact: {result.entries_checked:,} "
                     f"{'entry' if result.entries_checked == 1 else 'entries'} checked.")
    return Check(key="audit_chain", label="Audit log", status="problem",
                 detail=f"The chain breaks at entry {result.first_bad_seq}: {result.problem}.")


def _keys_check() -> Check:
    data_dir = Path(settings.data_dir)
    if not Path(settings.master_key_path).exists() or not (data_dir / "db.key.enc").exists():
        return Check(key="keys", label="Keys", status="problem",
                     detail="The master key or the database key file is missing.")
    if not (data_dir / "backup.key.enc").exists():
        return Check(key="keys", label="Keys", status="warning",
                     detail="There's no backup key yet. It's made with the recovery kit.")
    master = key_id(load_master_key(settings.master_key_path))
    return Check(key="keys", label="Keys", status="ok",
                 detail=f"The master key ({master}), database and backup keys are in place.")


def _disk_check(total: int, free: int) -> Check:
    share = free / total if total else 0
    detail = f"{free / GIB:.1f} GB free of {total / GIB:.1f} GB ({share:.0%})."
    if share < LOW_DISK_FRACTION / 2 and free < LOW_DISK_BYTES / 2:
        status: Status = "problem"
    elif share < LOW_DISK_FRACTION or free < LOW_DISK_BYTES:
        status = "warning"
    else:
        status = "ok"
    return Check(key="disk", label="Disk space", status=status, detail=detail)


def _breach_check(enabled: bool) -> Check:
    label = "Breached-password check"
    if not enabled:
        return Check(key="breach_check", label=label, status="off",
                     detail="Switched off in Security.")
    if pwned.reachable():
        return Check(key="breach_check", label=label, status="ok",
                     detail="Have I Been Pwned answers.")
    return Check(key="breach_check", label=label, status="warning",
                 detail="Þing can't reach Have I Been Pwned, so new passwords can't be saved "
                 "until it can.")


def _worker_check(beat: datetime | None, failed: int, now: datetime,
                  stopped: datetime | None = None) -> Check:
    label = "Background worker"
    if beat is not None and stopped is not None and stopped >= beat:
        return Check(key="worker", label=label, status="problem",
                     detail=f"Stopped {_ago(stopped, now)}. Start it with ting start.")
    if beat is None:
        return Check(key="worker", label=label, status="problem",
                     detail="The worker hasn't started. Check the worker container.")
    quiet = now - beat
    if quiet > timedelta(minutes=5):
        return Check(key="worker", label=label, status="problem",
                     detail=f"Not heard from for {int(quiet.total_seconds() // 60)} minutes. "
                     "Check the worker container.")
    if failed:
        return Check(key="worker", label=label, status="warning",
                     detail=f"Running, but {failed} job{'s' if failed != 1 else ''} failed in the "
                     "last day.")
    return Check(key="worker", label=label, status="ok", detail="Running.")


def _run_worker(db: Session) -> Check:
    now = clock.utcnow()
    failed = db.scalar(select(func.count()).select_from(Job).where(
        Job.state == "failed", Job.finished_at > now - timedelta(days=1))) or 0
    return _worker_check(worker.last_beat(db), failed, now, worker.stopped_at(db))


def _ago(moment: datetime, now: datetime) -> str:
    hours = int((now - moment).total_seconds() // 3600)
    if hours < 1:
        return "less than an hour ago"
    if hours < 48:
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    return f"{hours // 24} days ago"


def _target_backup(where: str, done: Job | None, failed: Job | None,
                   now: datetime) -> tuple[Status, str]:
    """How backups to one target fare, in a sentence."""
    if failed is not None and (done is None or (failed.finished_at or now) > (
            done.finished_at or now)):
        return "problem", f"The last backup to {where} failed: {failed.error or 'no reason given'}"
    if done is None or done.finished_at is None:
        return "warning", f"No backup to {where} yet."
    age = now - done.finished_at
    said = f"Backed up {_ago(done.finished_at, now)} to {where}."
    if age > timedelta(days=2):
        return "problem", said
    if age > timedelta(hours=26):
        return "warning", said
    return "ok", said


WORST: dict[Status, int] = {"ok": 0, "off": 0, "warning": 1, "problem": 2}


def _backups_check(plan: Plan, results: list[tuple[Status, str]]) -> Check:
    label = "Backups"
    if not plan.targets:
        return Check(key="backups", label=label, status="warning",
                     detail="Switched off in Backups: nothing is being backed up.")
    status_: Status = max((s for s, _ in results), key=lambda s: WORST[s])
    detail = " ".join(said for _, said in results)
    if status_ == "ok" and all(t.kind == "local" for t in plan.targets):
        return Check(key="backups", label=label, status="warning", detail=detail + (
            " A backup on the same server doesn't survive losing it: keep one on an SMB "
            "share or S3-compatible storage."))
    return Check(key="backups", label=label, status=status_, detail=detail)


def _restore_test_check(last: Job | None, now: datetime) -> Check:
    label = "Restore test"
    if last is None or last.finished_at is None:
        return Check(key="restore_test", label=label, status="warning",
                     detail="Not tested yet. The worker tests one a week, after a backup.")
    if last.state == "failed":
        return Check(key="restore_test", label=label, status="problem",
                     detail=f"The last restore test failed: {last.error or 'no reason given'}")
    entries = (last.outcome() or {}).get("audit_entries", 0)
    detail = (f"Restored and checked {_ago(last.finished_at, now)}: the database, and "
              f"{entries:,} audit log entries.")
    if now - last.finished_at > timedelta(days=8):
        return Check(key="restore_test", label=label, status="warning", detail=detail)
    return Check(key="restore_test", label=label, status="ok", detail=detail)


def _stamps_check(result: audit_stamps.StampCheck, now: datetime) -> Check:
    label = "Audit log timestamp"
    if not result.ok:
        return Check(key="audit_stamps", label=label, status="problem",
                     detail=result.problem or "The timestamps don't match the log.")
    if result.latest is None:
        return Check(key="audit_stamps", label=label, status="warning",
                     detail="Not timestamped yet. The worker asks once a day.")
    latest = result.latest
    host = urlsplit(latest.tsa_url).hostname or latest.tsa_url
    detail = (f"Entry {latest.seq} timestamped {_ago(latest.stamped_at, now)} by {host}; "
              + ("the timestamp still matches the log." if result.stamps == 1 else
                 f"all {result.stamps:,} timestamps still match the log."))
    age = now - latest.stamped_at
    if age > timedelta(days=2):
        return Check(key="audit_stamps", label=label, status="problem", detail=detail)
    if age > timedelta(hours=26):
        return Check(key="audit_stamps", label=label, status="warning", detail=detail)
    return Check(key="audit_stamps", label=label, status="ok", detail=detail)


def _run_stamps(db: Session) -> Check:
    db.commit()
    with reading(engine_of(db)) as reader:
        return _stamps_check(audit_stamps.check(reader), clock.utcnow())


def _run_backups(db: Session) -> Check:
    plan, now = load_plan(db), clock.utcnow()
    return _backups_check(plan, [
        _target_backup(target.words(), latest(db, "backup", target, index == 0, "done"),
                       latest(db, "backup", target, index == 0, "failed"), now)
        for index, target in enumerate(plan.targets)])


def _run_restore_test(db: Session) -> Check:
    """The oldest of the targets' newest restore tests: each must keep passing."""
    plan, now = load_plan(db), clock.utcnow()
    tests = [latest(db, "restore_test", target, index == 0, "done", "failed")
             for index, target in enumerate(plan.targets)]
    if not tests:
        return _restore_test_check(None, now)
    done = [t for t in tests if t is not None]
    failed = [t for t in done if t.state == "failed"]
    if failed or len(done) < len(tests):
        return _restore_test_check(failed[0] if failed else None, now)
    return _restore_test_check(min(done, key=lambda t: t.finished_at or now), now)


def _run_database(db: Session) -> Check:
    db.commit()  # the check reads every page: hold no write lock meanwhile
    return _database_check(check_integrity(engine_of(db)))


def _run_audit_chain(db: Session) -> Check:
    db.commit()
    with reading(engine_of(db)) as reader:
        return _audit_check(audit.verify(reader))


def _run_keys(db: Session) -> Check:
    return _keys_check()


def _run_disk(db: Session) -> Check:
    disk = shutil.disk_usage(Path(settings.data_dir))
    return _disk_check(disk.total, disk.free)


def _run_breach_check(db: Session) -> Check:
    enabled = load_policy(db).breach_check_enabled
    db.commit()  # a network call follows
    return _breach_check(enabled)


# Each check has its own request, so the page fills in as answers arrive and a
# slow one (the integrity check, the network) holds up nothing else.
CHECKS: dict[str, Callable[[Session], Check]] = {
    "database": _run_database,
    "audit_chain": _run_audit_chain,
    "audit_stamps": _run_stamps,
    "keys": _run_keys,
    "disk": _run_disk,
    "breach_check": _run_breach_check,
    "worker": _run_worker,
    "backups": _run_backups,
    "restore_test": _run_restore_test,
}


@router.get("/health")
def server_health(_: Admin, db: DB) -> ServerHealth:
    """Everything quick: usage, versions, and which checks there are to run."""
    completed = setup_completed_at(db)
    counts = {
        "users": db.scalar(select(func.count()).select_from(User)) or 0,
        "active_users": db.scalar(
            select(func.count()).select_from(User).where(User.is_active)
        ) or 0,
        "sessions": db.scalar(
            select(func.count()).select_from(UserSession).where(UserSession.ended_reason.is_(None))
        ) or 0,
        "audit_entries": db.scalar(select(func.max(AuditEntry.seq))) or 0,
        "images_bytes": db.scalar(select(func.sum(func.length(StoredImage.data)))) or 0,
    }
    schema = db.execute(text("SELECT version_num FROM alembic_version")).scalar()
    sqlite_version = str(db.execute(text("SELECT sqlite_version()")).scalar())
    sqlcipher_version = str(db.execute(text("PRAGMA cipher_version")).scalar())
    db.commit()

    data_dir = Path(settings.data_dir)
    disk = shutil.disk_usage(data_dir)
    database_bytes = sum(
        _file_size(data_dir / name) for name in ("ting.db", "ting.db-wal", "ting.db-shm")
    )
    return ServerHealth(
        checked_at=clock.utcnow(),
        started_at=STARTED_AT,
        address=settings.address,
        setup_completed_at=completed,
        checks=list(CHECKS),
        usage=Usage(disk_total_bytes=disk.total, disk_free_bytes=disk.free,
                    database_bytes=database_bytes, **counts),
        versions=Versions(
            ting=ting_version(),
            python=platform.python_version(),
            sqlite=sqlite_version,
            sqlcipher=sqlcipher_version,
            schema_version=schema,
            operating_system=_operating_system(),
            kernel=platform.release(),
        ),
        packages=_packages(),
    )


@router.get("/health/checks/{key}")
def run_check(key: str, _: Admin, db: DB) -> Check:
    check = CHECKS.get(key)
    if check is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "There's no such check.")
    return check(db)
