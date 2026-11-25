"""The work log API: a customer's entries, logging work, and the CSV export.

Everyone who sees the customer in full reads its log and logs work
(EDIT_CUSTOMERS); an entry is changed or removed by its author or by someone
who manages customers. Entries are sealed, so searching and filtering run here,
over the opened entries of the period asked for. Adding, changing, removing and
exporting are logged.
"""

from __future__ import annotations

import csv
import io
from datetime import datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import audit, clock
from app.auth.dependencies import DB, FullSession, client_ip, require
from app.auth.sessions import UserSession
from app.customer_routes import visible_customer
from app.customers import Customer, Keyring, may_manage
from app.roles import Capability, roles_of
from app.users import User
from app.worklog import (
    CustomerLogEntry,
    LogEntryIn,
    LogEntryOut,
    LogKind,
    LogSummary,
    describe,
    entries_of,
    sealed_fields,
    summarise,
    when,
    work_day,
)

router = APIRouter(prefix="/customers")
Editor = Annotated[UserSession, Depends(require(Capability.EDIT_CUSTOMERS))]

Period = Literal["90d", "year", "all"]
PERIODS: dict[Period, timedelta | None] = {
    "90d": timedelta(days=90), "year": timedelta(days=365), "all": None}
# A spreadsheet treats a cell starting with one of these as a formula (CSV injection).
FORMULA_STARTS = ("=", "+", "-", "@", "\t", "\r")
CSV_COLUMNS = ("When (UTC)", "Who", "Type", "What was done", "Service", "Systems", "Case number",
               "Coverage", "On site", "Ticket")


class LogPage(BaseModel):
    entries: list[LogEntryOut]
    # How many match, of which `entries` is a page.
    total: int
    # The last 90 days, whatever the filters.
    summary: LogSummary


class Filters:
    """What the Work log page narrows by; the export takes the same."""

    def __init__(
        self,
        period: Period = "90d",
        q: Annotated[str, Query(max_length=200)] = "",
        service_id: int | None = None,
        system_id: int | None = None,
        kind: LogKind | None = None,
        author_id: int | None = None,
        billable: bool = False,
    ) -> None:
        self.period, self.q, self.service_id, self.system_id = period, q, service_id, system_id
        self.kind, self.author_id, self.billable = kind, author_id, billable

    def since(self) -> datetime | None:
        span = PERIODS[self.period]
        return clock.utcnow() - span if span else None

    def keep(self, entry: LogEntryOut) -> bool:
        needle = self.q.strip().casefold()
        text = " ".join([entry.text, entry.service or "", entry.case_number, entry.ticket,
                         entry.author or "", *entry.systems]).casefold()
        return (
            (not needle or needle in text)
            and (self.service_id is None or entry.service_id == self.service_id)
            and (self.system_id is None or self.system_id in entry.system_ids)
            and (self.kind is None or entry.kind == self.kind)
            and (self.author_id is None or entry.author_id == self.author_id)
            and (not self.billable or entry.coverage == "billable")
        )

    def said(self) -> dict[str, str]:
        chosen = {"period": self.period, "q": self.q, "service": self.service_id,
                  "system": self.system_id, "kind": self.kind, "author": self.author_id,
                  "billable": self.billable or None}
        return {name: str(value) for name, value in chosen.items() if value}


def _log(db: Session, request: Request, record: UserSession, action: str, customer_id: int,
         details: dict[str, object]) -> None:
    audit.append(db, action, actor_id=record.user.id, actor_name=record.user.username,
                 target_type="customer", target_id=str(customer_id), ip=client_ip(request),
                 details=details)


def _matching(db: Session, record: UserSession, customer: Customer, filters: Filters
              ) -> list[LogEntryOut]:
    manages = may_manage(roles_of(db, record.user_id))
    entries = entries_of(db, Keyring().sealer(customer), customer.id, viewer_id=record.user_id,
                         manages=manages, since=filters.since())
    return [entry for entry in entries if filters.keep(entry)]


@router.get("/{customer_id}/log")
def list_entries(customer_id: int, request: Request, record: FullSession, db: DB,
                 filters: Annotated[Filters, Depends()],
                 limit: Annotated[int, Query(ge=1, le=500)] = 200,
                 offset: Annotated[int, Query(ge=0)] = 0) -> LogPage:
    customer, _ = visible_customer(db, request, record, customer_id)
    found = _matching(db, record, customer, filters)
    recent = entries_of(db, Keyring().sealer(customer), customer.id, viewer_id=record.user_id,
                        manages=False, since=clock.utcnow() - timedelta(days=90))
    return LogPage(entries=found[offset:offset + limit], total=len(found),
                   summary=summarise(recent))


@router.post("/{customer_id}/log")
def add_entry(customer_id: int, body: LogEntryIn, request: Request, author: Editor, db: DB
              ) -> LogEntryOut:
    customer, _ = visible_customer(db, request, author, customer_id)
    sealer = Keyring().sealer(customer)
    moment = when(body)
    fields = sealed_fields(db, sealer, customer, body, work_day(body, moment))
    entry = CustomerLogEntry(customer_id=customer.id, happened_at=moment,
                             author_id=author.user_id, sealed=b"")
    db.add(entry)
    db.flush()
    entry.sealed = sealer.seal("log", entry.id, fields)
    _log(db, request, author, "customer.log_added", customer.id, {"entry": entry.id})
    db.commit()
    return describe(entry, fields, {author.user_id: author.user.display_name}, True)


def _own(db: Session, record: UserSession, customer: Customer, entry_id: int) -> CustomerLogEntry:
    """The entry, if this person may change it: its author, or someone who manages
    customers."""
    entry = db.get(CustomerLogEntry, entry_id)
    if entry is None or entry.customer_id != customer.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That log entry doesn't exist.")
    if entry.author_id != record.user_id and not may_manage(roles_of(db, record.user_id)):
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Only its author or a Manager changes a log entry.")
    return entry


@router.put("/{customer_id}/log/{entry_id}")
def change_entry(customer_id: int, entry_id: int, body: LogEntryIn, request: Request,
                 editor: Editor, db: DB) -> LogEntryOut:
    customer, _ = visible_customer(db, request, editor, customer_id)
    entry = _own(db, editor, customer, entry_id)
    sealer = Keyring().sealer(customer)
    if body.happened_at is not None:
        entry.happened_at = when(body)
    # Covered or billable is worked out again, for the day the entry now says.
    fields = sealed_fields(db, sealer, customer, body, work_day(body, entry.happened_at))
    entry.sealed = sealer.seal("log", entry.id, fields)
    _log(db, request, editor, "customer.log_changed", customer.id, {"entry": entry.id})
    db.commit()
    author = db.get(User, entry.author_id) if entry.author_id is not None else None
    return describe(entry, fields, {author.id: author.display_name} if author else {}, True)


@router.delete("/{customer_id}/log/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_entry(customer_id: int, entry_id: int, request: Request, editor: Editor, db: DB
                 ) -> None:
    customer, _ = visible_customer(db, request, editor, customer_id)
    db.delete(_own(db, editor, customer, entry_id))
    _log(db, request, editor, "customer.log_removed", customer.id, {"entry": entry_id})
    db.commit()


def _cell(value: object) -> str:
    text = "" if value is None else str(value)
    return f"'{text}" if text.startswith(FORMULA_STARTS) else text


@router.get("/{customer_id}/log/export")
def export_csv(customer_id: int, request: Request, record: FullSession, db: DB,
               filters: Annotated[Filters, Depends()]) -> Response:
    """The entries shown, as CSV to open in a spreadsheet."""
    customer, _ = visible_customer(db, request, record, customer_id)
    found = _matching(db, record, customer, filters)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(CSV_COLUMNS)
    for entry in found:
        writer.writerow([_cell(value) for value in (
            entry.happened_at.strftime("%Y-%m-%d %H:%M"), entry.author, entry.kind, entry.text,
            entry.service, ", ".join(entry.systems), entry.case_number, entry.coverage,
            "yes" if entry.on_site else "", entry.ticket)])
    _log(db, request, record, "customer.log_exported", customer.id,
         {"rows": len(found), "filters": filters.said()})
    db.commit()
    day = clock.utcnow().strftime("%Y%m%d")
    return Response(
        # A byte order mark, so Excel reads æ, ø and å as UTF-8.
        content="﻿" + buffer.getvalue(), media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="ting-work-log-{day}.csv"',
                 "Cache-Control": "no-store"},
    )
