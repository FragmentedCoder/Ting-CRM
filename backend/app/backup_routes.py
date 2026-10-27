"""Backups in the admin panel: where they go, when, for how long, and how they fare.

Administrators only. Backups can go to several targets at once, each backed up
and tested on its own. Changing where backups go always asks the person to
confirm it's them, since it sends every copy of the data somewhere else. Secrets
are written, never read back: the page only learns whether one is set. Running a
backup, a restore test or a connection check queues a job for the worker (one
per target); the page follows them by asking for the jobs.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit, clock, jobs
from app.admin import Admin
from app.auth.dependencies import DB, client_ip, require_step_up
from app.auth.sessions import UserSession
from app.backups import (
    SECRETS,
    Plan,
    Target,
    latest,
    load_plan,
    load_target_secrets,
    next_backup,
    repository,
    save_plan,
)
from app.jobs import Job
from app.sealed_settings import save_secrets
from app.users import User

router = APIRouter(prefix="/admin/backups")

KINDS = ("backup", "restore_test", "backup_check")
# Each kind's secret, as the form sends it and as it's sealed.
SECRET_OF = {"smb": "smb_password", "s3": "s3_secret_access_key"}


class TargetIn(Target):
    # Left out (None) for a target that's new: it gets one.
    id: str | None = Field(default=None, pattern=r"^[a-z0-9-]{1,40}$")  # type: ignore[assignment]
    # Left out (None) keeps what's kept; an empty string clears it.
    smb_password: str | None = Field(default=None, max_length=200)
    s3_secret_access_key: str | None = Field(default=None, max_length=200)


class PlanIn(BaseModel):
    hour: int = Field(default=2, ge=0, le=23)
    keep_days: int = Field(default=90, ge=7, le=3650)
    targets: list[TargetIn] = Field(default_factory=list, max_length=5)


class Run(BaseModel):
    id: int
    kind: str
    target: str | None
    state: str
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    result: dict[str, Any] | None
    error: str | None
    requested_by: str | None


class TargetStatus(BaseModel):
    target: Target
    # As a sentence names it, such as "the SMB share \\\\nas\\backups".
    words: str
    secret_set: bool
    repository: str
    last_backup: Run | None
    last_restore_test: Run | None


class BackupStatus(BaseModel):
    hour: int
    keep_days: int
    targets: list[TargetStatus]
    next_backup_at: datetime | None
    runs: list[Run]


def _run(db: Session, job: Job) -> Run:
    who = db.get(User, job.requested_by) if job.requested_by else None
    by = who.display_name if who else (
        "The ting command" if job.data().get("via") == "console" else None)
    return Run(id=job.id, kind=job.kind, target=job.data().get("target"), state=job.state,
               created_at=job.created_at, started_at=job.started_at,
               finished_at=job.finished_at, result=job.outcome(), error=job.error,
               requested_by=by)


def _log(db: Session, request: Request, admin: UserSession, action: str,
         details: dict[str, Any] | None = None) -> None:
    audit.append(db, action, actor_id=admin.user.id, actor_name=admin.user.username,
                 ip=client_ip(request), details=details)


def _status(db: Session) -> BackupStatus:
    plan = load_plan(db)
    secrets = load_target_secrets(db, plan)
    now = clock.utcnow()
    targets = []
    for index, target in enumerate(plan.targets):
        backed_up = latest(db, "backup", target, index == 0, "done")
        tested = latest(db, "restore_test", target, index == 0, "done", "failed")
        secret = SECRET_OF.get(target.kind)
        targets.append(TargetStatus(
            target=target, words=target.words(), repository=repository(target),
            secret_set=bool(secret and secrets.get(target.id, {}).get(secret)),
            last_backup=_run(db, backed_up) if backed_up else None,
            last_restore_test=_run(db, tested) if tested else None))
    done_today = bool(targets) and all(
        t.last_backup and t.last_backup.finished_at
        and t.last_backup.finished_at.date() == now.date() for t in targets)
    runs = db.scalars(select(Job).where(Job.kind.in_(KINDS))
                      .order_by(Job.created_at.desc(), Job.id.desc()).limit(20))
    return BackupStatus(hour=plan.hour, keep_days=plan.keep_days, targets=targets,
                        next_backup_at=next_backup(plan, done_today, now),
                        runs=[_run(db, job) for job in runs])


@router.get("")
def backup_status(_: Admin, db: DB) -> BackupStatus:
    return _status(db)


@router.put("")
def change_plan(body: PlanIn, request: Request, admin: Admin, db: DB) -> BackupStatus:
    return apply_plan(db, request, admin, body, confirm=True)


def _new_id(kind: str, taken: set[str]) -> str:
    if kind not in taken:
        return kind
    number = 2
    while f"{kind}-{number}" in taken:
        number += 1
    return f"{kind}-{number}"


def apply_plan(db: Session, request: Request, admin: UserSession, body: PlanIn,
               confirm: bool) -> BackupStatus:
    """Save where backups go, when, and for how long; with confirm, changing where
    they go asks for step-up (the setup wizard saves without: the one setting up has
    just signed in)."""
    before = load_plan(db)
    kept = load_target_secrets(db, before)
    taken = {t.id for t in body.targets if t.id}
    if len(taken) != len([t for t in body.targets if t.id]):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Two targets have the same ID.")
    if sum(t.kind == "local" for t in body.targets) > 1:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This server can be a target once.")
    targets: list[Target] = []
    secrets: dict[str, dict[str, str]] = {}
    typed = False
    for given in body.targets:
        target_id = given.id or _new_id(given.kind, taken)
        taken.add(target_id)
        target = Target.model_validate(given.model_dump(
            exclude={"smb_password", "s3_secret_access_key"}) | {"id": target_id})
        own = dict(kept.get(target_id, {})) if given.id else {}
        for field in SECRET_OF.values():
            if (value := getattr(given, field)) is not None:
                own[field] = value
                typed = True
        if missing := target.missing():
            raise HTTPException(status.HTTP_400_BAD_REQUEST, missing)
        if target.kind == "smb" and not own.get("smb_password"):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "An SMB share needs its password.")
        if target.kind == "s3" and not own.get("s3_secret_access_key"):
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                "S3-compatible storage needs its secret key.")
        targets.append(target)
        secrets[target_id] = own
    plan = Plan(hour=body.hour, keep_days=body.keep_days, targets=targets)

    def where(p: Plan) -> set[tuple[str, str]]:
        return {(t.id, repository(t)) for t in p.targets}

    if confirm and (where(plan) != where(before) or typed):
        require_step_up(admin, "Confirm it's you to change where backups go.")
    save_plan(db, plan)
    save_secrets(db, SECRETS, secrets)
    _log(db, request, admin, "backup.settings_changed", {
        "hour": plan.hour, "keep_days": plan.keep_days,
        "targets": [t.kind for t in plan.targets]})
    db.commit()
    return _status(db)


def _queue(db: Session, request: Request, admin: UserSession, kind: str,
           target_id: str | None) -> list[Run]:
    plan = load_plan(db)
    if not plan.targets:
        raise HTTPException(status.HTTP_409_CONFLICT, "Backups are switched off.")
    chosen = plan.targets if target_id is None else [t for t in plan.targets if t.id == target_id]
    if not chosen:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "There's no such backup target.")
    runs = []
    for target in chosen:
        waiting = next((job for job in db.scalars(select(Job).where(
            Job.kind == kind, Job.state.in_(("queued", "running"))))
            if job.data().get("target", plan.targets[0].id) == target.id), None)
        if waiting is None:
            waiting = jobs.enqueue(db, kind, {"target": target.id}, requested_by=admin.user.id)
            _log(db, request, admin, f"backup.{kind}_requested",
                 {"job": waiting.id, "target": target.id})
        runs.append(waiting)
    db.commit()
    return [_run(db, job) for job in runs]


Action = Literal["backup", "restore_test", "backup_check"]


@router.post("/run/{kind}")
def run_now(kind: Action, request: Request, admin: Admin, db: DB,
            target: str | None = None) -> list[Run]:
    """Back up now, test a restore now, or check a target can be reached: for one
    target, or each of them."""
    return _queue(db, request, admin, kind, target)


@router.get("/runs/{run_id}")
def get_run(run_id: int, _: Admin, db: DB) -> Run:
    job = db.get(Job, run_id)
    if job is None or job.kind not in KINDS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "There's no such run.")
    return _run(db, job)
