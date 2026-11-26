"""What needs attention at a customer, worked out from what's on record.

Nothing is stored for it. A customer's standing is gathered from its tasks,
renewals, agreements and services with today's date, and the rules turn it into
reasons, most urgent first: overdue tasks; a renewal past its date; a renewal
within 30 days that isn't approved; an agreement's last notice day within 60
days; active services no agreement covers. Compliance and hand-over plans join
these in Phase 3.

My work (app/mywork.py) reads it for the customers someone works with, and All
customers reads it, with each customer's services, for every customer someone
sees in full.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import clock
from app.agreements import CustomerAgreement, agreements_of, coverage
from app.auth.dependencies import DB, require
from app.auth.sessions import UserSession
from app.customer_services import CustomerServiceOut, services_of
from app.customers import (
    Customer,
    Keyring,
    assigned_customer_ids,
    is_limited,
    level_for,
    sights,
)
from app.planning import CustomerRenewal, CustomerTask
from app.roles import Capability, roles_of

router = APIRouter(prefix="/attention")
Worker = Annotated[UserSession, Depends(require(Capability.EDIT_CUSTOMERS))]

# How far ahead renewals and agreement dates are gathered, and the rules' own reach.
AHEAD_DAYS = 60
RENEWAL_DAYS = 30
NOTICE_DAYS = 60
REASONS_SHOWN = 3


class Reason(BaseModel):
    """Why a customer needs attention; the page puts it into words."""

    kind: Literal["tasks_overdue", "renewal_overdue", "renewal_soon", "notice", "uncovered"]
    tone: Literal["critical", "warning"]
    # How many (tasks, renewals, services), and the first one's name and day.
    count: int = 1
    what: str = ""
    day: date | None = None


@dataclass
class AgreementDate:
    day: date
    name: str
    agreement_id: int = 0
    # For an end: whether the agreement renews by itself then.
    auto_renews: bool = False


@dataclass
class Standing:
    """What's on record about one customer that the rules, My work and All customers
    read. Tasks and renewals come with their rows; the rest is opened only for the
    customers asked for in detail."""

    # Not yet done, soonest first.
    open_tasks: list[CustomerTask] = field(default_factory=list)
    overdue_tasks: int = 0
    # Still to deal with (not renewed, not run out as decided) and within reach, or
    # waiting for the customer however far off; each with what it is.
    renewals: list[tuple[CustomerRenewal, str]] = field(default_factory=list)
    # Active agreements' last notice days and ends within reach.
    notices: list[AgreementDate] = field(default_factory=list)
    ends: list[AgreementDate] = field(default_factory=list)
    # The active services, and the names of those no agreement covers.
    services: list[CustomerServiceOut] = field(default_factory=list)
    uncovered: list[str] = field(default_factory=list)


def standings(db: Session, keyring: Keyring, customers: dict[int, Customer], today: date,
              detailed: set[int], horizon: date | None = None) -> dict[int, Standing]:
    """Each customer's standing. Agreements and services are opened for the customers
    in `detailed` only. Renewals and agreement dates are gathered up to `horizon`:
    as far as the rules reach unless given (My work gives the team's own reach)."""
    found = {customer_id: Standing() for customer_id in customers}
    sealers = {customer_id: keyring.sealer(customer)
               for customer_id, customer in customers.items()}
    horizon = horizon or today + timedelta(days=AHEAD_DAYS)

    for task in db.scalars(select(CustomerTask).where(CustomerTask.done_at.is_(None))
                           .order_by(CustomerTask.due_on, CustomerTask.id)):
        if (standing := found.get(task.customer_id)) is None:
            continue
        standing.open_tasks.append(task)
        standing.overdue_tasks += task.due_on < today

    for renewal in db.scalars(select(CustomerRenewal)
                              .where(CustomerRenewal.decision != "renewed")
                              .order_by(CustomerRenewal.renews_on, CustomerRenewal.id)):
        if (standing := found.get(renewal.customer_id)) is None:
            continue
        if renewal.decision == "declined" and renewal.renews_on < today:
            continue
        if renewal.renews_on > horizon and renewal.decision != "waiting":
            continue
        what = str(sealers[renewal.customer_id].open("renewal", renewal.id, renewal.sealed)
                   .get("what", ""))
        standing.renewals.append((renewal, what))

    for agreement in db.scalars(select(CustomerAgreement)
                                .where(CustomerAgreement.status == "active")):
        customer_id = agreement.customer_id
        if customer_id not in detailed or customer_id not in found:
            continue
        notice = agreement.notice_by is not None and today <= agreement.notice_by <= horizon
        ending = agreement.ends_on is not None and today <= agreement.ends_on <= horizon
        if not notice and not ending:
            continue
        name = str(sealers[customer_id].open("agreement", agreement.id, agreement.sealed)
                   .get("name", ""))
        if notice and agreement.notice_by is not None:
            found[customer_id].notices.append(
                AgreementDate(agreement.notice_by, name, agreement.id))
        if ending and agreement.ends_on is not None:
            found[customer_id].ends.append(
                AgreementDate(agreement.ends_on, name, agreement.id, agreement.auto_renews))

    for customer_id in detailed & found.keys():
        sealer = sealers[customer_id]
        standing = found[customer_id]
        standing.services = [s for s in services_of(db, sealer, customer_id)
                             if s.status == "active"]
        covered = coverage(agreements_of(db, sealer, customer_id))
        standing.uncovered = [s.name for s in standing.services if s.id not in covered]
        standing.notices.sort(key=lambda found_date: found_date.day)
    return found


def reasons(standing: Standing, today: date) -> list[Reason]:
    """A customer's reasons, most urgent first."""
    found: list[Reason] = []
    if standing.overdue_tasks:
        found.append(Reason(kind="tasks_overdue", tone="critical", count=standing.overdue_tasks))
    past = [(r, what) for r, what in standing.renewals if r.renews_on < today]
    if past:
        found.append(Reason(kind="renewal_overdue", tone="critical", count=len(past),
                            what=past[0][1], day=past[0][0].renews_on))
    soon = [(r, what) for r, what in standing.renewals
            if today <= r.renews_on <= today + timedelta(days=RENEWAL_DAYS)
            and r.decision != "approved"]
    if soon:
        found.append(Reason(kind="renewal_soon", tone="warning", count=len(soon),
                            what=soon[0][1], day=soon[0][0].renews_on))
    notices = [n for n in standing.notices if n.day <= today + timedelta(days=NOTICE_DAYS)]
    if notices:
        found.append(Reason(kind="notice", tone="warning", count=len(notices),
                            what=notices[0].name, day=notices[0].day))
    if standing.uncovered:
        found.append(Reason(kind="uncovered", tone="warning", count=len(standing.uncovered),
                            what=standing.uncovered[0]))
    return found


class CustomerStanding(BaseModel):
    """One row of All customers: how many services, and what needs attention."""

    customer_id: int
    # Active services, and how many of them no agreement covers.
    services: int
    uncovered: int
    # The most urgent reasons, at most three, and how many more there are.
    reasons: list[Reason]
    more: int = 0


@router.get("")
def attention(worker: Worker, db: DB) -> list[CustomerStanding]:
    """Every customer this person sees in full: its services and what needs
    attention. A former customer has neither."""
    sight = sights(roles_of(db, worker.user_id), is_limited(db, worker.user_id))
    assigned = assigned_customer_ids(db, worker.user_id)
    seen = {c.id: c for c in db.scalars(select(Customer))
            if level_for(sight, c.id in assigned) == "full" and c.status != "former"}
    today = clock.utcnow().date()
    found = []
    for customer_id, standing in standings(db, Keyring(), seen, today, set(seen)).items():
        why = reasons(standing, today)
        found.append(CustomerStanding(
            customer_id=customer_id, services=len(standing.services),
            uncovered=len(standing.uncovered), reasons=why[:REASONS_SHOWN],
            more=max(0, len(why) - REASONS_SHOWN)))
    return found
