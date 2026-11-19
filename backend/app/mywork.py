"""My work: where the day starts.

Across the customers someone works with: the tasks that are theirs, the renewals
and notice days coming up, and the customers that need attention. Nothing is
stored for it. It's worked out from the tasks, renewals, agreements and services
each time, with today's date, and only from customers the person sees in full.

**Whose a task is:** the people it names; the customer's technicians (those who
usually work with it, or every technician when nobody does); or the Managers
(everyone who manages customers).

**My customers** are the ones someone usually works with. Someone who manages
customers, or who isn't assigned to any, gets every customer they see. Former
customers are left out.

**What needs attention**, most urgent first and at most three per customer:
overdue tasks; a renewal past its date; a renewal within 30 days that isn't
approved; an agreement's last notice day within 60 days; active services no
agreement covers. Compliance and hand-over plans join these in Phase 3.

Managers also get what's theirs to deal with: renewals waiting for a customer's
answer, monthly case numbers not yet replaced this month, and services no
agreement covers.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select

from app import clock
from app.agreements import CustomerAgreement, agreements_of, coverage
from app.auth.dependencies import DB, require
from app.auth.sessions import UserSession
from app.customer_routes import Team
from app.customer_services import services_of
from app.customers import (
    Customer,
    Keyring,
    assigned_customer_ids,
    is_limited,
    level_for,
    may_manage,
    sights,
)
from app.planning import (
    CustomerRenewal,
    CustomerTask,
    CustomerTaskPerson,
    Decision,
    TaskOut,
    describe_task,
)
from app.roles import Capability, Role, roles_of

router = APIRouter(prefix="/my-work")
Worker = Annotated[UserSession, Depends(require(Capability.EDIT_CUSTOMERS))]

AHEAD_DAYS = 60
RENEWAL_DAYS = 30
NOTICE_DAYS = 60
REASONS_SHOWN = 3


class MyTask(BaseModel):
    customer_id: int
    customer: str
    task: TaskOut


class Dated(BaseModel):
    """Something with a date on a customer: a renewal, or an agreement's last notice
    day or its end."""

    customer_id: int
    customer: str
    kind: Literal["renewal", "notice", "ends", "renews"]
    what: str
    day: date
    # A renewal's decision so far.
    decision: Decision | None = None


class Reason(BaseModel):
    """Why a customer needs attention; the page puts it into words."""

    kind: Literal["tasks_overdue", "renewal_overdue", "renewal_soon", "notice", "uncovered"]
    tone: Literal["critical", "warning"]
    # How many (tasks, renewals, services), and the first one's name and day.
    count: int = 1
    what: str = ""
    day: date | None = None


class Attention(BaseModel):
    customer_id: int
    customer: str
    # The most urgent, at most three.
    reasons: list[Reason]
    more: int = 0


class Counts(BaseModel):
    overdue: int
    this_week: int
    dates: int
    attention: int


class MonthlyCase(BaseModel):
    customer_id: int
    customer: str
    service: str
    case_number: str
    since: date | None


class Uncovered(BaseModel):
    customer_id: int
    customer: str
    services: list[str]


class ForManagers(BaseModel):
    # Renewals waiting for a customer's answer.
    waiting: list[Dated]
    # Monthly case numbers given before this month began.
    monthly_cases: list[MonthlyCase]
    # Active services no agreement covers.
    uncovered: list[Uncovered]


class MyWork(BaseModel):
    today: date
    tasks: list[MyTask]
    dates: list[Dated]
    attention: list[Attention]
    counts: Counts
    managers: ForManagers | None = None


def _reasons(overdue_tasks: int, renewals: list[tuple[CustomerRenewal, str]],
             notices: list[Dated], uncovered: list[str], today: date) -> list[Reason]:
    """A customer's reasons, most urgent first."""
    reasons: list[Reason] = []
    if overdue_tasks:
        reasons.append(Reason(kind="tasks_overdue", tone="critical", count=overdue_tasks))
    past = [(r, what) for r, what in renewals if r.renews_on < today]
    if past:
        reasons.append(Reason(kind="renewal_overdue", tone="critical", count=len(past),
                              what=past[0][1], day=past[0][0].renews_on))
    soon = [(r, what) for r, what in renewals
            if today <= r.renews_on <= today + timedelta(days=RENEWAL_DAYS)
            and r.decision != "approved"]
    if soon:
        reasons.append(Reason(kind="renewal_soon", tone="warning", count=len(soon),
                              what=soon[0][1], day=soon[0][0].renews_on))
    if notices:
        reasons.append(Reason(kind="notice", tone="warning", count=len(notices),
                              what=notices[0].what, day=notices[0].day))
    if uncovered:
        reasons.append(Reason(kind="uncovered", tone="warning", count=len(uncovered),
                              what=uncovered[0]))
    return reasons


@router.get("")
def my_work(worker: Worker, db: DB) -> MyWork:
    today = clock.utcnow().date()
    me = worker.user_id
    roles = roles_of(db, me)
    manages = may_manage(roles)
    technician = Role.TECHNICIAN in roles
    sight = sights(roles, is_limited(db, me))
    assigned = assigned_customer_ids(db, me)
    team = Team(db)
    keyring = Keyring()

    seen = {c.id: c for c in db.scalars(select(Customer))
            if level_for(sight, c.id in assigned) == "full" and c.status != "former"}
    mine = set(seen) if manages or not (assigned & set(seen)) else assigned & set(seen)
    names = {customer_id: keyring.details(customer)["name"]
             for customer_id, customer in seen.items()}
    sealers = {customer_id: keyring.sealer(customer) for customer_id, customer in seen.items()}

    # Tasks: mine, wherever they are; and how many are overdue on each customer.
    named = set(db.scalars(select(CustomerTaskPerson.task_id)
                           .where(CustomerTaskPerson.user_id == me)))
    tasks: list[MyTask] = []
    overdue: dict[int, int] = {}
    for row in db.scalars(select(CustomerTask).where(CustomerTask.done_at.is_(None))
                          .order_by(CustomerTask.due_on, CustomerTask.id)):
        if row.customer_id not in seen:
            continue
        if row.due_on < today:
            overdue[row.customer_id] = overdue.get(row.customer_id, 0) + 1
        held = team.of(row.customer_id)
        for_me = (row.id in named if row.audience == "people"
                  else manages if row.audience == "managers"
                  else me in held or (technician and not held))
        if for_me:
            sealed = sealers[row.customer_id].open("task", row.id, row.sealed)
            tasks.append(MyTask(customer_id=row.customer_id, customer=names[row.customer_id],
                                task=describe_task(db, row, sealed, me, manages)))

    # Renewals still to deal with: not renewed, and not run out as decided.
    horizon = today + timedelta(days=AHEAD_DAYS)
    renewals: dict[int, list[tuple[CustomerRenewal, str]]] = {}
    for renewal in db.scalars(select(CustomerRenewal)
                              .where(CustomerRenewal.decision != "renewed")
                              .order_by(CustomerRenewal.renews_on, CustomerRenewal.id)):
        if renewal.customer_id not in seen:
            continue
        if renewal.decision == "declined" and renewal.renews_on < today:
            continue
        if renewal.renews_on > horizon and renewal.decision != "waiting":
            continue
        what = str(sealers[renewal.customer_id].open("renewal", renewal.id, renewal.sealed)
                   .get("what", ""))
        renewals.setdefault(renewal.customer_id, []).append((renewal, what))

    def dated(customer_id: int, kind: Literal["renewal", "notice", "ends", "renews"], what: str,
              day: date, decision: Decision | None = None) -> Dated:
        return Dated(customer_id=customer_id, customer=names[customer_id], kind=kind, what=what,
                     day=day, decision=decision)

    # Agreements' notice days and ends in the coming weeks.
    notices: dict[int, list[Dated]] = {}
    ends: list[Dated] = []
    for agreement in db.scalars(select(CustomerAgreement)
                                .where(CustomerAgreement.status == "active")):
        customer_id = agreement.customer_id
        if customer_id not in mine:
            continue
        notice = agreement.notice_by is not None and today <= agreement.notice_by <= horizon
        ending = agreement.ends_on is not None and today <= agreement.ends_on <= horizon
        if not notice and not ending:
            continue
        name = str(sealers[customer_id].open("agreement", agreement.id, agreement.sealed)
                   .get("name", ""))
        if notice and agreement.notice_by is not None:
            notices.setdefault(customer_id, []).append(
                dated(customer_id, "notice", name, agreement.notice_by))
        if ending and agreement.ends_on is not None:
            ends.append(dated(customer_id, "renews" if agreement.auto_renews else "ends", name,
                              agreement.ends_on))

    dates = [dated(customer_id, "renewal", what, renewal.renews_on,
                   renewal.decision)  # type: ignore[arg-type]
             for customer_id, found in renewals.items() if customer_id in mine
             for renewal, what in found if renewal.renews_on <= horizon]
    dates += [notice for found in notices.values() for notice in found] + ends
    dates.sort(key=lambda d: (d.day, d.customer.casefold(), d.what.casefold()))

    # What each of my customers needs, and what no agreement covers.
    attention: list[Attention] = []
    uncovered: list[Uncovered] = []
    monthly: list[MonthlyCase] = []
    month_start = today.replace(day=1)
    for customer_id in sorted(seen if manages else mine, key=lambda c: names[c].casefold()):
        sealer = sealers[customer_id]
        services = [s for s in services_of(db, sealer, customer_id) if s.status == "active"]
        covered = coverage(agreements_of(db, sealer, customer_id))
        bare = [s.name for s in services if s.id not in covered]
        if bare:
            uncovered.append(Uncovered(customer_id=customer_id, customer=names[customer_id],
                                       services=bare))
        monthly += [MonthlyCase(customer_id=customer_id, customer=names[customer_id],
                                service=s.name, case_number=s.case_number, since=s.case_since)
                    for s in services if s.case_kind == "monthly" and s.case_number
                    and (s.case_since is None or s.case_since < month_start)]
        if customer_id not in mine:
            continue
        reasons = _reasons(overdue.get(customer_id, 0), renewals.get(customer_id, []),
                           [n for n in notices.get(customer_id, [])
                            if n.day <= today + timedelta(days=NOTICE_DAYS)], bare, today)
        if reasons:
            attention.append(Attention(
                customer_id=customer_id, customer=names[customer_id],
                reasons=reasons[:REASONS_SHOWN], more=max(0, len(reasons) - REASONS_SHOWN)))
    # The most urgent customers first: those with something critical, then by name.
    attention.sort(key=lambda a: (a.reasons[0].tone != "critical", a.customer.casefold()))

    week = today + timedelta(days=7)
    counts = Counts(
        overdue=sum(1 for t in tasks if t.task.due_on < today),
        this_week=sum(1 for t in tasks if today <= t.task.due_on <= week),
        dates=len(dates), attention=len(attention),
    )
    managers = None
    if manages:
        waiting = [dated(customer_id, "renewal", what, renewal.renews_on, "waiting")
                   for customer_id, found in renewals.items()
                   for renewal, what in found if renewal.decision == "waiting"]
        waiting.sort(key=lambda d: (d.day, d.customer.casefold()))
        managers = ForManagers(waiting=waiting, monthly_cases=monthly, uncovered=uncovered)
    return MyWork(today=today, tasks=tasks, dates=dates, attention=attention, counts=counts,
                  managers=managers)
