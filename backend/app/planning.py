"""What's coming up for a customer: tasks, recurring work and renewals.

A **task** has a title, a due date and someone it's for: named people, the
customer's technicians (whoever usually works with it), or the Managers. A
**recurring task** (updates every three months, a restore test every six) also has
a rhythm; ticking it off writes a work log entry and schedules the next one,
counted from the day it was done.

A **renewal** is something that runs out on a date: a licence, a firewall
feature key, a certificate, a warranty. It records the date, how often it
renews, how long before to warn and whom, and the decision: Approved (the
customer and a Manager agreed), Waiting for the customer, Renewed, or Won't be
renewed, with the reason and what must be done before it runs out, which
becomes a task. Dates only: no prices, and never the key itself.

What a task or renewal says is sealed with the customer's key. Its dates, its
state and who it's for stay plain: My work, warnings and the wall display need
them across customers without opening each one. The routes are in
app/planning_routes.py.
"""

from __future__ import annotations

import calendar
from datetime import date, datetime
from typing import Any, Literal

from fastapi import HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import Date, ForeignKey, Integer, LargeBinary, String, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.customer_services import CustomerService
from app.customers import (
    Customer,
    CustomerAssignment,
    CustomerSystem,
    Sealer,
    level_for,
    sights,
)
from app.db import Base, UTCDateTime
from app.roles import Role, UserRole
from app.users import User

Audience = Literal["people", "technicians", "managers"]
Decision = Literal["", "approved", "waiting", "renewed", "declined"]
RenewalKind = Literal["licence", "antivirus", "feature_key", "certificate", "warranty",
                      "subscription", "domain", "other"]


class CustomerTask(Base):
    __tablename__ = "customer_tasks"
    __table_args__ = {"sqlite_autoincrement": True}

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), index=True
    )
    due_on: Mapped[date] = mapped_column(Date, index=True)
    done_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    done_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    # Who it's for: named people (customer_task_people), the customer's
    # technicians, or the Managers.
    audience: Mapped[str] = mapped_column(String(12), default="technicians")
    # {"title", "notes", "service_id", "system_id", "ticket", "every", "renewal_id"}
    sealed: Mapped[bytes] = mapped_column(LargeBinary)


class CustomerTaskPerson(Base):
    __tablename__ = "customer_task_people"

    task_id: Mapped[int] = mapped_column(
        ForeignKey("customer_tasks.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True
    )


class CustomerRenewal(Base):
    __tablename__ = "customer_renewals"
    __table_args__ = {"sqlite_autoincrement": True}

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), index=True
    )
    renews_on: Mapped[date] = mapped_column(Date, index=True)
    # "" until someone decides; see Decision.
    decision: Mapped[str] = mapped_column(String(10), default="")
    # How many days before to warn, and whom.
    warn_days: Mapped[int] = mapped_column(Integer, default=30)
    audience: Mapped[str] = mapped_column(String(12), default="managers")
    # {"what", "kind", "service_id", "system_id", "supplier", "every", "reason",
    #  "fallback", "notes"}
    sealed: Mapped[bytes] = mapped_column(LargeBinary)


class CustomerRenewalPerson(Base):
    __tablename__ = "customer_renewal_people"

    renewal_id: Mapped[int] = mapped_column(
        ForeignKey("customer_renewals.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True
    )


class Every(BaseModel):
    """A rhythm: every so many weeks or months."""

    count: int = Field(ge=1, le=120)
    unit: Literal["weeks", "months"] = "months"


class Who(BaseModel):
    id: int
    display_name: str


class TaskIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    # What to do, or what's special: "Also update the booking service on APP01".
    notes: str = Field(default="", max_length=2000)
    due_on: date
    audience: Audience = "technicians"
    # With audience "people": who.
    people: list[int] = Field(default=[], max_length=20)
    service_id: int | None = None
    system_id: int | None = None
    ticket: str = Field(default="", max_length=40)
    # A recurring task's rhythm.
    every: Every | None = None


class TaskOut(BaseModel):
    id: int
    title: str
    notes: str
    due_on: date
    audience: Audience
    people: list[Who]
    service_id: int | None
    service: str | None
    system_id: int | None
    system: str | None
    ticket: str
    every: Every | None
    # The renewal it was made by ("switch off web filtering if the key isn't renewed").
    renewal_id: int | None
    # Whoever made it, or someone who manages customers, may remove it.
    may_remove: bool = False


class RenewalIn(BaseModel):
    what: str = Field(min_length=1, max_length=200)
    kind: RenewalKind = "other"
    renews_on: date
    every: Every | None = None
    warn_days: int = Field(default=30, ge=0, le=365)
    audience: Audience = "managers"
    people: list[int] = Field(default=[], max_length=20)
    service_id: int | None = None
    system_id: int | None = None
    supplier: str = Field(default="", max_length=150)
    notes: str = Field(default="", max_length=2000)


class RenewalOut(RenewalIn):
    id: int
    decision: Decision
    # Why it won't be renewed, and what must be done before it runs out.
    reason: str
    fallback: str
    service: str | None
    system: str | None
    who: list[Who]


def add_interval(day: date, every: Every) -> date:
    """The day one interval later; a month's end stays in its month (31 Jan + 1
    month is 28 or 29 Feb)."""
    if every.unit == "weeks":
        return date.fromordinal(day.toordinal() + 7 * every.count)
    months = day.month - 1 + every.count
    year, month = day.year + months // 12, months % 12 + 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def _named(db: Session, sealer: Sealer, customer: Customer, service_id: int | None,
           system_id: int | None) -> tuple[str, str]:
    """The service's and system's names, each checked as this customer's."""
    service_name = system_name = ""
    if service_id is not None:
        service = db.get(CustomerService, service_id)
        if service is None or service.customer_id != customer.id:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                                "That service doesn't exist.")
        service_name = str(sealer.open("service", service.id, service.sealed).get("name", ""))
    if system_id is not None:
        system = db.get(CustomerSystem, system_id)
        if system is None or system.customer_id != customer.id:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                                "That system doesn't exist.")
        system_name = str(sealer.open("system", system.id, system.sealed).get("name", ""))
    return service_name, system_name


def colleagues(db: Session, customer_id: int) -> list[Who]:
    """The people a task or renewal can name: everyone who can sign in and sees this
    customer in full. That's the Administrators, the Managers and the technicians,
    except a technician limited to other customers."""
    assigned = set(db.scalars(select(CustomerAssignment.user_id)
                              .where(CustomerAssignment.customer_id == customer_id)))
    rows = db.execute(select(User, UserRole.role).join(UserRole, UserRole.user_id == User.id)
                      .where(User.is_active).order_by(User.display_name, User.id))
    found: dict[int, Who] = {}
    for user, role in rows:
        sight = sights({Role(role)}, user.limited_to_assigned)
        if level_for(sight, user.id in assigned) == "full":
            found.setdefault(user.id, Who(id=user.id, display_name=user.display_name))
    return list(found.values())


def chosen_people(db: Session, customer_id: int, audience: Audience, people: list[int]
                  ) -> list[int]:
    """The people a task or renewal names: among the customer's colleagues, and at
    least one when it's for named people."""
    if audience != "people":
        return []
    ids = list(dict.fromkeys(people))
    if not ids or not set(ids) <= {who.id for who in colleagues(db, customer_id)}:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                            "Choose who it's for, among the people who work with this customer.")
    return ids


def task_fields(db: Session, sealer: Sealer, customer: Customer, body: TaskIn,
                renewal_id: int | None = None) -> dict[str, Any]:
    service_name, system_name = _named(db, sealer, customer, body.service_id, body.system_id)
    return {
        "title": body.title.strip(), "notes": body.notes.strip(), "service_id": body.service_id,
        "service_name": service_name, "system_id": body.system_id, "system_name": system_name,
        "ticket": body.ticket.strip(),
        "every": body.every.model_dump() if body.every else None, "renewal_id": renewal_id,
    }


def renewal_fields(db: Session, sealer: Sealer, customer: Customer, body: RenewalIn,
                   before: dict[str, Any]) -> dict[str, Any]:
    service_name, system_name = _named(db, sealer, customer, body.service_id, body.system_id)
    return {
        "what": body.what.strip(), "kind": body.kind, "service_id": body.service_id,
        "service_name": service_name, "system_id": body.system_id, "system_name": system_name,
        "supplier": body.supplier.strip(),
        "every": body.every.model_dump() if body.every else None,
        "reason": before.get("reason", ""), "fallback": before.get("fallback", ""),
        "notes": body.notes.strip(),
    }


def _who(db: Session, ids: list[int]) -> list[Who]:
    if not ids:
        return []
    rows = db.execute(select(User.id, User.display_name).where(User.id.in_(ids))
                      .order_by(User.display_name))
    return [Who(id=user_id, display_name=name) for user_id, name in rows]


def _audience(value: str) -> Audience:
    return "people" if value == "people" else "managers" if value == "managers" else "technicians"


def describe_task(db: Session, row: CustomerTask, sealed: dict[str, Any],
                  viewer_id: int | None = None, manages: bool = False) -> TaskOut:
    people = list(db.scalars(select(CustomerTaskPerson.user_id)
                             .where(CustomerTaskPerson.task_id == row.id)))
    return TaskOut(
        id=row.id, title=str(sealed.get("title", "")), notes=str(sealed.get("notes", "")),
        due_on=row.due_on, audience=_audience(row.audience), people=_who(db, people),
        service_id=sealed.get("service_id"), service=sealed.get("service_name") or None,
        system_id=sealed.get("system_id"), system=sealed.get("system_name") or None,
        ticket=str(sealed.get("ticket", "")),
        every=Every.model_validate(sealed["every"]) if sealed.get("every") else None,
        renewal_id=sealed.get("renewal_id"),
        may_remove=manages or (viewer_id is not None and row.created_by == viewer_id),
    )


def open_tasks(db: Session, sealer: Sealer, customer_id: int, viewer_id: int | None = None,
               manages: bool = False) -> list[TaskOut]:
    """The customer's tasks not yet done, soonest first."""
    rows = db.scalars(select(CustomerTask)
                      .where(CustomerTask.customer_id == customer_id,
                             CustomerTask.done_at.is_(None))
                      .order_by(CustomerTask.due_on, CustomerTask.id))
    return [describe_task(db, row, sealer.open("task", row.id, row.sealed), viewer_id, manages)
            for row in rows]


def describe_renewal(db: Session, row: CustomerRenewal, sealed: dict[str, Any]) -> RenewalOut:
    people = list(db.scalars(select(CustomerRenewalPerson.user_id)
                             .where(CustomerRenewalPerson.renewal_id == row.id)))
    decision: Decision = row.decision if row.decision in (  # type: ignore[assignment]
        "approved", "waiting", "renewed", "declined") else ""
    return RenewalOut(
        id=row.id, what=str(sealed.get("what", "")), kind=sealed.get("kind", "other"),
        renews_on=row.renews_on,
        every=Every.model_validate(sealed["every"]) if sealed.get("every") else None,
        warn_days=row.warn_days, audience=_audience(row.audience), people=people,
        service_id=sealed.get("service_id"), system_id=sealed.get("system_id"),
        supplier=str(sealed.get("supplier", "")), notes=str(sealed.get("notes", "")),
        decision=decision, reason=str(sealed.get("reason", "")),
        fallback=str(sealed.get("fallback", "")),
        service=sealed.get("service_name") or None, system=sealed.get("system_name") or None,
        who=_who(db, people),
    )


def renewals_of(db: Session, sealer: Sealer, customer_id: int) -> list[RenewalOut]:
    """The customer's renewals, soonest first."""
    rows = db.scalars(select(CustomerRenewal).where(CustomerRenewal.customer_id == customer_id)
                      .order_by(CustomerRenewal.renews_on, CustomerRenewal.id))
    return [describe_renewal(db, row, sealer.open("renewal", row.id, row.sealed))
            for row in rows]
