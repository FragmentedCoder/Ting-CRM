"""Reading the audit log: Administrators and Auditors (READ_AUDIT_LOG).

Checking it re-hashes the chain and checks every daily timestamp against it (see
app/audit_stamps.py). Administrators choose the timestamp authority and can ask
for a timestamp now.
"""

# No `from __future__ import annotations` here: FastAPI resolves the Filters class's
# annotations at runtime, and a class has no globals to resolve postponed ones from.
import csv
import io
import json
from collections.abc import Iterator
from datetime import UTC, date, datetime, time, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import ColumnElement, Engine, func, select

from app import audit, audit_stamps, jobs
from app.admin import Admin
from app.audit import AuditEntry, timestamp
from app.auth.dependencies import DB, client_ip, require
from app.auth.sessions import UserSession
from app.db import engine_of, reading
from app.jobs import Job
from app.policy import Setting
from app.roles import Capability
from app.users import normalize_username

router = APIRouter(prefix="/audit")

Auditor = Annotated[UserSession, Depends(require(Capability.READ_AUDIT_LOG))]
PAGE_SIZE = 50
EXPORT_BATCH = 1000
CSV_COLUMNS = ("seq", "occurred_at", "actor_id", "actor_name", "action", "target_type",
               "target_id", "ip", "details", "hash")
# A spreadsheet treats a cell starting with one of these as a formula (CSV injection).
FORMULA_STARTS = ("=", "+", "-", "@", "\t", "\r")


class AuditEntryOut(BaseModel):
    seq: int
    occurred_at: str
    actor_name: str | None
    action: str
    target_type: str | None
    target_id: str | None
    ip: str | None
    details: dict[str, Any]


class AuditPage(BaseModel):
    entries: list[AuditEntryOut]
    next_before: int | None


class ChainStatus(BaseModel):
    ok: bool
    entries_checked: int
    first_bad_seq: int | None
    problem: str | None
    # The daily timestamps: how many, the newest, and whether they all still hold.
    stamps: int
    stamps_ok: bool
    stamp_problem: str | None
    last_stamped_seq: int | None
    last_stamped_at: datetime | None
    tsa_url: str


class TsaIn(BaseModel):
    tsa_url: str = Field(max_length=300, pattern=r"^https?://[^\s]+$")


class StampRun(BaseModel):
    id: int
    state: str
    result: dict[str, Any] | None
    error: str | None


class Filters:
    """The same filters for the list and the export. An action ending in `.*` matches a group."""

    def __init__(
        self,
        action: str | None = None,
        actor: str | None = None,
        since: date | None = None,
        until: date | None = None,
    ) -> None:
        self.values = {"action": action, "actor": actor, "since": since, "until": until}
        self.clauses: list[ColumnElement[bool]] = []
        if action and action.endswith(".*"):
            self.clauses.append(AuditEntry.action.startswith(action[:-1], autoescape=True))
        elif action:
            self.clauses.append(AuditEntry.action == action)
        if actor:
            self.clauses.append(AuditEntry.actor_name == normalize_username(actor))
        if since:
            self.clauses.append(AuditEntry.occurred_at >= _day_start(since))
        if until:
            self.clauses.append(AuditEntry.occurred_at < _day_start(until + timedelta(days=1)))


def _day_start(day: date) -> str:
    return timestamp(datetime.combine(day, time.min, tzinfo=UTC))


def _out(entry: AuditEntry) -> AuditEntryOut:
    return AuditEntryOut(
        seq=entry.seq, occurred_at=entry.occurred_at, actor_name=entry.actor_name,
        action=entry.action, target_type=entry.target_type, target_id=entry.target_id,
        ip=entry.ip, details=json.loads(entry.details),
    )


@router.get("")
def list_entries(
    _: Auditor,
    db: DB,
    filters: Annotated[Filters, Depends()],
    before: int | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = PAGE_SIZE,
) -> AuditPage:
    query = select(AuditEntry).where(*filters.clauses)
    if before is not None:
        query = query.where(AuditEntry.seq < before)
    rows = list(db.scalars(query.order_by(AuditEntry.seq.desc()).limit(limit + 1)))
    more = len(rows) > limit
    rows = rows[:limit]
    return AuditPage(entries=[_out(e) for e in rows], next_before=rows[-1].seq if more else None)


@router.get("/actions")
def list_actions(_: Auditor, db: DB) -> list[str]:
    return list(db.scalars(select(AuditEntry.action).distinct().order_by(AuditEntry.action)))


@router.get("/verify")
def verify_chain(_: Auditor, db: DB) -> ChainStatus:
    db.commit()  # re-hashing every entry takes a while: hold no write lock meanwhile
    with reading(engine_of(db)) as reader:
        check = audit.verify(reader)
        stamps = audit_stamps.check(reader)
        tsa = audit_stamps.tsa_url(reader)
    latest = stamps.latest
    return ChainStatus(ok=check.ok, entries_checked=check.entries_checked,
                       first_bad_seq=check.first_bad_seq, problem=check.problem,
                       stamps=stamps.stamps, stamps_ok=stamps.ok, stamp_problem=stamps.problem,
                       last_stamped_seq=latest.seq if latest else None,
                       last_stamped_at=latest.stamped_at if latest else None, tsa_url=tsa)


@router.put("/stamps/authority")
def change_authority(body: TsaIn, request: Request, admin: Admin, db: DB) -> ChainStatus:
    """Which timestamp authority stamps the log each day."""
    db.merge(Setting(key=audit_stamps.TSA_SETTING, value=body.tsa_url))
    audit.append(db, "audit.tsa_changed", actor_id=admin.user.id,
                 actor_name=admin.user.username, ip=client_ip(request),
                 details={"tsa": body.tsa_url})
    db.commit()
    return verify_chain(admin, db)


def _stamp_run(job: Job) -> StampRun:
    return StampRun(id=job.id, state=job.state, result=job.outcome(), error=job.error)


@router.post("/stamps/run")
def stamp_now(request: Request, admin: Admin, db: DB) -> StampRun:
    """Ask for a timestamp now, rather than at the day's turn."""
    waiting = db.scalar(select(Job).where(Job.kind == "audit_stamp",
                                          Job.state.in_(("queued", "running"))).limit(1))
    if waiting is not None:
        return _stamp_run(waiting)
    job = jobs.enqueue(db, "audit_stamp", requested_by=admin.user.id)
    audit.append(db, "audit.stamp_requested", actor_id=admin.user.id,
                 actor_name=admin.user.username, ip=client_ip(request), details={"job": job.id})
    db.commit()
    return _stamp_run(job)


@router.get("/stamps/runs/{run_id}")
def get_stamp_run(run_id: int, _: Admin, db: DB) -> StampRun:
    job = db.get(Job, run_id)
    if job is None or job.kind != "audit_stamp":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "There's no such run.")
    return _stamp_run(job)


def _cell(value: object) -> str:
    text = "" if value is None else str(value)
    return f"'{text}" if text.startswith(FORMULA_STARTS) else text


def _csv_line(values: list[str]) -> str:
    buffer = io.StringIO()
    csv.writer(buffer).writerow(values)
    return buffer.getvalue()


def _csv_rows(engine: Engine, clauses: list[ColumnElement[bool]], last_seq: int) -> Iterator[str]:
    """The export, a batch at a time, so a large log never sits in memory whole."""
    yield _csv_line(list(CSV_COLUMNS))
    with reading(engine) as reader:
        query = (select(AuditEntry).where(*clauses, AuditEntry.seq <= last_seq)
                 .order_by(AuditEntry.seq).execution_options(yield_per=EXPORT_BATCH))
        for entry in reader.scalars(query):
            yield _csv_line([_cell(getattr(entry, column)) for column in CSV_COLUMNS])


@router.get("/export")
def export_csv(
    request: Request, reader: Auditor, db: DB, filters: Annotated[Filters, Depends()]
) -> StreamingResponse:
    # Everything up to now; the entry recording this export comes after.
    last_seq = db.scalar(select(func.max(AuditEntry.seq))) or 0
    rows = db.scalar(select(func.count()).select_from(AuditEntry)
                     .where(*filters.clauses, AuditEntry.seq <= last_seq)) or 0
    audit.append(
        db, "audit.exported", actor_id=reader.user.id, actor_name=reader.user.username,
        ip=client_ip(request),
        details={"rows": rows, "filters": {k: str(v) for k, v in filters.values.items() if v}},
    )
    db.commit()
    day = datetime.now(UTC).strftime("%Y%m%d")
    return StreamingResponse(
        _csv_rows(engine_of(db), filters.clauses, last_seq),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="ting-audit-{day}.csv"'},
    )
