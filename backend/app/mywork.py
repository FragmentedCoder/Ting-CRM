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

**What needs attention** comes from the rules in app/attention.py, most urgent
first and at most three per customer.

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
from app.attention import REASONS_SHOWN, Reason, reasons, standings
from app.auth.dependencies import DB, require
from app.auth.sessions import UserSession
from app.customer_routes import Team
from app.customers import (
    Customer,
    Keyring,
    assigned_customer_ids,
    is_limited,
    level_for,
    may_manage,
    sights,
)
from app.general import ahead, general
from app.planning import CustomerTaskPerson, Decision, TaskOut, describe_task
from app.roles import Capability, Role, roles_of

router = APIRouter(prefix="/my-work")
Worker = Annotated[UserSession, Depends(require(Capability.EDIT_CUSTOMERS))]


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
    # The renewal's own ID, or the agreement's: the page links to it.
    id: int
    what: str
    day: date
    # A renewal's decision so far.
    decision: Decision | None = None


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
    service_id: int
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
    # How far ahead what's coming up reaches (the team's setting), and the last day
    # that's within it. Tasks due later aren't listed: `later` counts them.
    ahead_months: int
    ahead_until: date
    later: int
    tasks: list[MyTask]
    dates: list[Dated]
    attention: list[Attention]
    counts: Counts
    managers: ForManagers | None = None


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
    # What's coming up reaches as far ahead as the team has set: nearer always shows.
    horizon = ahead(db, today)
    # Agreements and services are opened for my customers; a Manager's are all of them.
    found = standings(db, keyring, seen, today, set(seen) if manages else mine, horizon)

    # Tasks: mine, wherever they are, soonest first.
    named = set(db.scalars(select(CustomerTaskPerson.task_id)
                           .where(CustomerTaskPerson.user_id == me)))
    tasks: list[MyTask] = []
    later = 0
    rows = sorted((row for standing in found.values() for row in standing.open_tasks),
                  key=lambda row: (row.due_on, row.id))
    for row in rows:
        held = team.of(row.customer_id)
        for_me = (row.id in named if row.audience == "people"
                  else manages if row.audience == "managers"
                  else me in held or (technician and not held))
        if for_me and row.due_on > horizon:
            later += 1
        elif for_me:
            sealed = keyring.sealer(seen[row.customer_id]).open("task", row.id, row.sealed)
            tasks.append(MyTask(customer_id=row.customer_id, customer=names[row.customer_id],
                                task=describe_task(db, row, sealed, me, manages)))

    def dated(customer_id: int, kind: Literal["renewal", "notice", "ends", "renews"], of: int,
              what: str, day: date, decision: Decision | None = None) -> Dated:
        return Dated(customer_id=customer_id, customer=names[customer_id], kind=kind, id=of,
                     what=what, day=day, decision=decision)

    # Renewals, last notice days and ends within that reach, at my customers.
    dates: list[Dated] = []
    for customer_id in mine:
        standing = found[customer_id]
        dates += [dated(customer_id, "renewal", renewal.id, what, renewal.renews_on,
                        renewal.decision)  # type: ignore[arg-type]
                  for renewal, what in standing.renewals if renewal.renews_on <= horizon]
        dates += [dated(customer_id, "notice", notice.agreement_id, notice.name, notice.day)
                  for notice in standing.notices]
        dates += [dated(customer_id, "renews" if end.auto_renews else "ends", end.agreement_id,
                        end.name, end.day)
                  for end in standing.ends]
    dates.sort(key=lambda d: (d.day, d.customer.casefold(), d.what.casefold()))

    # What each of my customers needs, and what's the Managers' to deal with.
    attention: list[Attention] = []
    uncovered: list[Uncovered] = []
    monthly: list[MonthlyCase] = []
    month_start = today.replace(day=1)
    for customer_id in sorted(seen if manages else mine, key=lambda c: names[c].casefold()):
        standing = found[customer_id]
        if standing.uncovered:
            uncovered.append(Uncovered(customer_id=customer_id, customer=names[customer_id],
                                       services=standing.uncovered))
        monthly += [MonthlyCase(customer_id=customer_id, customer=names[customer_id],
                                service_id=s.id, service=s.name, case_number=s.case_number,
                                since=s.case_since)
                    for s in standing.services if s.case_kind == "monthly" and s.case_number
                    and (s.case_since is None or s.case_since < month_start)]
        if customer_id not in mine:
            continue
        why = reasons(standing, today)
        if why:
            attention.append(Attention(
                customer_id=customer_id, customer=names[customer_id],
                reasons=why[:REASONS_SHOWN], more=max(0, len(why) - REASONS_SHOWN)))
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
        waiting = [dated(customer_id, "renewal", renewal.id, what, renewal.renews_on, "waiting")
                   for customer_id, standing in found.items()
                   for renewal, what in standing.renewals if renewal.decision == "waiting"]
        waiting.sort(key=lambda d: (d.day, d.customer.casefold()))
        managers = ForManagers(waiting=waiting, monthly_cases=monthly, uncovered=uncovered)
    return MyWork(today=today, ahead_months=general(db).warn_ahead_months, ahead_until=horizon,
                  later=later, tasks=tasks, dates=dates, attention=attention, counts=counts,
                  managers=managers)
