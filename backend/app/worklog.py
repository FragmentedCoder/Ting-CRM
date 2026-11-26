"""The work log: what was done for a customer, in plain text.

"Added a 5G backup router on the firewall's port 3 as failover": an entry is a
line of text with when it happened and who wrote it, its type (a call, work, a
visit, a meeting; later an uploaded email or document), and optionally the
service and systems it was about, the case number the time went on, whether it
was on site, and a ticket ID. Þing does no time registration, so an entry has no
duration.

An entry records whether the work was covered: Covered when an agreement that
ran on the day the work was done covers the service, Billable when none does.
It's the day of the work that counts, not the day it was recorded: work from
before an agreement began is billable, and work done while an agreement that has
since ended ran was covered. That, the service's and systems' names and the case
number are kept as they were when the entry was saved, so a later change to the
customer doesn't rewrite its history.

The text and everything about an entry are sealed with the customer's key; when
it happened and who wrote it stay plain, for ordering and the timeline. Everyone
who works with the customer logs work; an entry is changed or removed by its
author or by a Manager. The routes are in app/worklog_routes.py.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal

from fastapi import HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import ForeignKey, Index, LargeBinary, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from app import clock
from app.agreements import agreements_of, coverage
from app.customer_services import CustomerService
from app.customers import Customer, CustomerSystem, Sealer
from app.db import Base, UTCDateTime
from app.users import User

LogKind = Literal["call", "work", "visit", "meeting", "email", "document"]
Coverage = Literal["covered", "billable", ""]


class CustomerLogEntry(Base):
    __tablename__ = "customer_log"
    __table_args__ = (
        Index("ix_customer_log_customer_when", "customer_id", "happened_at"),
        {"sqlite_autoincrement": True},
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id", ondelete="CASCADE"))
    happened_at: Mapped[datetime] = mapped_column(UTCDateTime)
    author_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    # {"kind", "text", "service_id", "service_name", "system_ids", "system_names",
    #  "case_number", "coverage", "on_site", "ticket"}
    sealed: Mapped[bytes] = mapped_column(LargeBinary)


class LogEntryIn(BaseModel):
    kind: LogKind = "work"
    # When it happened; now when left out.
    happened_at: datetime | None = None
    # The day that was for the person who did it (the app sends it): east of
    # Greenwich it's already tomorrow there. Left out, the moment's day in UTC.
    happened_on: date | None = None
    text: str = Field(min_length=1, max_length=2000)
    service_id: int | None = None
    system_ids: list[int] = Field(default=[], max_length=50)
    # Left out, the service's own case number is taken.
    case_number: str | None = Field(default=None, max_length=30, pattern=r"^[A-Za-z0-9\-/]*$")
    on_site: bool = False
    # The team's ticket system's ID, as plain text.
    ticket: str = Field(default="", max_length=40)

    @field_validator("happened_at")
    @classmethod
    def _aware(cls, value: datetime | None) -> datetime | None:
        return value.replace(tzinfo=UTC) if value is not None and value.tzinfo is None else value


class LogEntryOut(BaseModel):
    id: int
    kind: LogKind
    happened_at: datetime
    author_id: int | None
    author: str | None
    text: str
    service_id: int | None
    service: str | None
    system_ids: list[int]
    systems: list[str]
    case_number: str
    coverage: Coverage
    on_site: bool
    ticket: str
    # Its author, or someone who manages customers.
    may_change: bool = False


class LogSummary(BaseModel):
    """The last 90 days at a glance."""

    entries: int
    on_site: int
    people: int
    billable: int
    by_service: list[tuple[str, int]]


def sealed_fields(db: Session, sealer: Sealer, customer: Customer, body: LogEntryIn,
                  day: date) -> dict[str, Any]:
    """What's sealed for an entry: its service and systems checked as this
    customer's, named and numbered as they are now, and covered or billable by the
    agreements that ran on the day the work was done."""
    service_name, case_number, covered = "", body.case_number or "", ""
    if body.service_id is not None:
        service = db.get(CustomerService, body.service_id)
        if service is None or service.customer_id != customer.id:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                                "That service doesn't exist.")
        opened = sealer.open("service", service.id, service.sealed)
        service_name = str(opened.get("name", ""))
        if body.case_number is None:
            case_number = str(opened.get("case_number", ""))
        by_agreement = coverage(agreements_of(db, sealer, customer.id), on=day)
        covered = "covered" if service.id in by_agreement else "billable"
    names: list[str] = []
    for system_id in dict.fromkeys(body.system_ids):
        system = db.get(CustomerSystem, system_id)
        if system is None or system.customer_id != customer.id:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                                "That system doesn't exist.")
        names.append(str(sealer.open("system", system.id, system.sealed).get("name", "")))
    return {
        "kind": body.kind, "text": body.text.strip(), "service_id": body.service_id,
        "service_name": service_name, "system_ids": list(dict.fromkeys(body.system_ids)),
        "system_names": names, "case_number": case_number.strip(), "coverage": covered,
        "on_site": body.on_site, "ticket": body.ticket.strip(),
    }


# How far a person's clock may run ahead of the server's before "now" is refused.
CLOCK_SLACK = timedelta(minutes=5)


def when(body: LogEntryIn) -> datetime:
    """When the entry happened: now unless given, and never ahead of time. Work that
    hasn't happened yet can't be logged: planned work is a task, not a log entry."""
    now = clock.utcnow()
    moment = body.happened_at or now
    if moment > now + CLOCK_SLACK:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                            "Work can't be logged ahead of time: it's logged once it's done. "
                            "Plan ahead with a task.")
    return min(moment, now)


def work_day(body: LogEntryIn, moment: datetime) -> date:
    """The day the work was done, which decides the agreement that covered it: the
    person's own day when the app gives it and it's the moment's (within a day, for
    time zones), else the moment's day in UTC."""
    day = moment.astimezone(UTC).date()
    if body.happened_on is not None and abs((body.happened_on - day).days) <= 1:
        return body.happened_on
    return day


def describe(row: CustomerLogEntry, sealed: dict[str, Any], authors: dict[int, str],
             may_change: bool) -> LogEntryOut:
    return LogEntryOut(
        id=row.id, kind=sealed.get("kind", "work"), happened_at=row.happened_at,
        author_id=row.author_id, author=authors.get(row.author_id or -1),
        text=str(sealed.get("text", "")), service_id=sealed.get("service_id"),
        service=sealed.get("service_name") or None,
        system_ids=list(sealed.get("system_ids", [])),
        systems=list(sealed.get("system_names", [])),
        case_number=str(sealed.get("case_number", "")), coverage=sealed.get("coverage", ""),
        on_site=bool(sealed.get("on_site", False)), ticket=str(sealed.get("ticket", "")),
        may_change=may_change,
    )


def entries_of(db: Session, sealer: Sealer, customer_id: int, *, viewer_id: int, manages: bool,
               since: datetime | None = None, limit: int | None = None) -> list[LogEntryOut]:
    """The customer's entries, newest first."""
    query = (select(CustomerLogEntry).where(CustomerLogEntry.customer_id == customer_id)
             .order_by(CustomerLogEntry.happened_at.desc(), CustomerLogEntry.id.desc()))
    if since is not None:
        query = query.where(CustomerLogEntry.happened_at >= since)
    if limit is not None:
        query = query.limit(limit)
    rows = list(db.scalars(query))
    ids = {row.author_id for row in rows if row.author_id is not None}
    authors = {user_id: name for user_id, name in db.execute(
        select(User.id, User.display_name).where(User.id.in_(ids)))}
    return [describe(row, sealer.open("log", row.id, row.sealed), authors,
                     manages or row.author_id == viewer_id) for row in rows]


def summarise(entries: list[LogEntryOut]) -> LogSummary:
    by_service: dict[str, int] = {}
    for entry in entries:
        if entry.service:
            by_service[entry.service] = by_service.get(entry.service, 0) + 1
    return LogSummary(
        entries=len(entries),
        on_site=sum(1 for e in entries if e.on_site),
        people=len({e.author_id for e in entries if e.author_id is not None}),
        billable=sum(1 for e in entries if e.coverage == "billable"),
        by_service=sorted(by_service.items(), key=lambda item: (-item[1], item[0])),
    )
