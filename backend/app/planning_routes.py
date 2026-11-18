"""The API for a customer's tasks and renewals (app/planning.py).

Everyone who works with a customer adds tasks, reschedules them and ticks them
off, records renewals and marks them renewed (EDIT_CUSTOMERS). A task is
removed by whoever made it or by someone who manages customers. The decision on
a renewal (Approved, Waiting for the customer, Won't be renewed) is for those
who manage customers (MANAGE_CUSTOMERS), and so is removing one. Ticking off a
task and deciding or marking a renewal write a work log entry; every change is
in the audit log. Each answers with the customer's detail, like the customer's
other routes.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app import audit, clock
from app.auth.dependencies import DB, client_ip, require
from app.auth.sessions import UserSession
from app.customer_routes import CustomerDetail, _detail, visible_customer
from app.customer_services import CustomerService
from app.customers import Customer, Keyring, Sealer, may_manage
from app.planning import (
    CustomerRenewal,
    CustomerRenewalPerson,
    CustomerTask,
    CustomerTaskPerson,
    Every,
    RenewalIn,
    TaskIn,
    add_interval,
    chosen_people,
    renewal_fields,
    task_fields,
)
from app.roles import Capability, roles_of
from app.worklog import CustomerLogEntry

router = APIRouter(prefix="/customers")
Editor = Annotated[UserSession, Depends(require(Capability.EDIT_CUSTOMERS))]
Manager = Annotated[UserSession, Depends(require(Capability.MANAGE_CUSTOMERS))]

REASONS = {"declined": "the customer declined", "not_approved": "it wasn't approved",
           "no_answer": "the customer didn't answer", "not_paid": "it wasn't paid"}


class Done(BaseModel):
    # What was done, for the work log; the task's title when left out.
    note: str = Field(default="", max_length=2000)
    # The day it was done; today when left out.
    done_on: date | None = None


class DecisionIn(BaseModel):
    decision: Literal["", "approved", "waiting", "declined"]
    # With "declined": why, and what must be done before it runs out.
    reason: Literal["", "declined", "not_approved", "no_answer", "not_paid"] = ""
    fallback: str = Field(default="", max_length=300)
    # When the fallback must be done; two days before it runs out when left out.
    fallback_due: date | None = None


class Renewed(BaseModel):
    note: str = Field(default="", max_length=2000)
    # When it renews next; one interval on when left out.
    next_on: date | None = None


def _log(db: Session, request: Request, record: UserSession, action: str, customer_id: int,
         details: dict[str, object]) -> None:
    audit.append(db, action, actor_id=record.user.id, actor_name=record.user.username,
                 target_type="customer", target_id=str(customer_id), ip=client_ip(request),
                 details=details)


def _note(db: Session, sealer: Sealer, customer: Customer, record: UserSession, text: str,
          sealed: dict[str, Any]) -> None:
    """A work log entry for something done from a task or renewal, about its service
    and system."""
    service_id = sealed.get("service_id")
    case_number = ""
    if service_id is not None:
        service = db.get(CustomerService, service_id)
        if service is not None:
            case_number = str(sealer.open("service", service.id, service.sealed)
                              .get("case_number", ""))
    entry = CustomerLogEntry(customer_id=customer.id, happened_at=clock.utcnow(),
                             author_id=record.user_id, sealed=b"")
    db.add(entry)
    db.flush()
    system_id = sealed.get("system_id")
    entry.sealed = sealer.seal("log", entry.id, {
        "kind": "work", "text": text, "service_id": service_id,
        "service_name": sealed.get("service_name", ""),
        "system_ids": [system_id] if system_id is not None else [],
        "system_names": [sealed["system_name"]] if sealed.get("system_name") else [],
        "case_number": case_number, "coverage": "", "on_site": False,
        "ticket": sealed.get("ticket", ""),
    })


def _set_people(db: Session, model: type[CustomerTaskPerson] | type[CustomerRenewalPerson],
                column: str, owner_id: int, people: list[int]) -> None:
    db.execute(delete(model).where(getattr(model, column) == owner_id))
    for user_id in people:
        db.add(model(**{column: owner_id, "user_id": user_id}))


# Tasks


def _task(db: Session, customer: Customer, task_id: int) -> CustomerTask:
    task = db.get(CustomerTask, task_id)
    if task is None or task.customer_id != customer.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That task doesn't exist.")
    return task


def _new_task(db: Session, sealer: Sealer, customer: Customer, body: TaskIn,
              created_by: int | None, renewal_id: int | None = None) -> CustomerTask:
    people = chosen_people(db, customer.id, body.audience, body.people)
    fields = task_fields(db, sealer, customer, body, renewal_id)
    task = CustomerTask(customer_id=customer.id, due_on=body.due_on, audience=body.audience,
                        created_by=created_by, sealed=b"")
    db.add(task)
    db.flush()
    task.sealed = sealer.seal("task", task.id, fields)
    _set_people(db, CustomerTaskPerson, "task_id", task.id, people)
    return task


@router.post("/{customer_id}/tasks")
def add_task(customer_id: int, body: TaskIn, request: Request, editor: Editor, db: DB
             ) -> CustomerDetail:
    customer, _ = visible_customer(db, request, editor, customer_id)
    keyring = Keyring()
    task = _new_task(db, keyring.sealer(customer), customer, body, editor.user_id)
    _log(db, request, editor, "customer.task_added", customer.id, {"task": task.id})
    db.commit()
    return _detail(db, editor, keyring, customer, "full")


@router.put("/{customer_id}/tasks/{task_id}")
def change_task(customer_id: int, task_id: int, body: TaskIn, request: Request, editor: Editor,
                db: DB) -> CustomerDetail:
    """Change a task that isn't done yet: what it says, when it's due, who it's for."""
    customer, _ = visible_customer(db, request, editor, customer_id)
    task = _task(db, customer, task_id)
    if task.done_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "That task is done.")
    keyring = Keyring()
    sealer = keyring.sealer(customer)
    people = chosen_people(db, customer.id, body.audience, body.people)
    before = sealer.open("task", task.id, task.sealed)
    fields = task_fields(db, sealer, customer, body, before.get("renewal_id"))
    changes: dict[str, object] = {"task": task.id}
    if task.due_on != body.due_on:
        changes["due"] = [task.due_on.isoformat(), body.due_on.isoformat()]
    task.due_on, task.audience = body.due_on, body.audience
    task.sealed = sealer.seal("task", task.id, fields)
    _set_people(db, CustomerTaskPerson, "task_id", task.id, people)
    _log(db, request, editor, "customer.task_changed", customer.id, changes)
    db.commit()
    return _detail(db, editor, keyring, customer, "full")


@router.post("/{customer_id}/tasks/{task_id}/done")
def finish_task(customer_id: int, task_id: int, body: Done, request: Request, editor: Editor,
                db: DB) -> CustomerDetail:
    """Tick a task off: it goes to the work log, and a recurring one comes back, one
    interval after the day it was done."""
    customer, _ = visible_customer(db, request, editor, customer_id)
    task = _task(db, customer, task_id)
    if task.done_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "That task is already done.")
    today = clock.utcnow().date()
    done_on = body.done_on or today
    if done_on > today:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                            "A task is done today or earlier.")
    keyring = Keyring()
    sealer = keyring.sealer(customer)
    sealed = sealer.open("task", task.id, task.sealed)
    task.done_at, task.done_by = clock.utcnow(), editor.user_id
    title = str(sealed.get("title", ""))
    note = body.note.strip()
    _note(db, sealer, customer, editor, f"{title}: {note}" if note else f"{title}: done.", sealed)
    details: dict[str, object] = {"task": task.id}
    if sealed.get("every"):
        every = Every.model_validate(sealed["every"])
        people = list(db.scalars(select(CustomerTaskPerson.user_id)
                                 .where(CustomerTaskPerson.task_id == task.id)))
        again = CustomerTask(customer_id=customer.id, due_on=add_interval(done_on, every),
                             audience=task.audience, created_by=task.created_by, sealed=b"")
        db.add(again)
        db.flush()
        again.sealed = sealer.seal("task", again.id, sealed)
        _set_people(db, CustomerTaskPerson, "task_id", again.id, people)
        details["next"] = again.id
    _log(db, request, editor, "customer.task_done", customer.id, details)
    db.commit()
    return _detail(db, editor, keyring, customer, "full")


@router.delete("/{customer_id}/tasks/{task_id}")
def remove_task(customer_id: int, task_id: int, request: Request, editor: Editor, db: DB
                ) -> CustomerDetail:
    customer, _ = visible_customer(db, request, editor, customer_id)
    task = _task(db, customer, task_id)
    if task.created_by != editor.user_id and not may_manage(roles_of(db, editor.user_id)):
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Only whoever made a task, or a Manager, removes it.")
    db.delete(task)
    _log(db, request, editor, "customer.task_removed", customer.id, {"task": task_id})
    db.commit()
    return _detail(db, editor, Keyring(), customer, "full")


# Renewals


def _renewal(db: Session, customer: Customer, renewal_id: int) -> CustomerRenewal:
    renewal = db.get(CustomerRenewal, renewal_id)
    if renewal is None or renewal.customer_id != customer.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That renewal doesn't exist.")
    return renewal


@router.post("/{customer_id}/renewals")
def add_renewal(customer_id: int, body: RenewalIn, request: Request, editor: Editor, db: DB
                ) -> CustomerDetail:
    customer, _ = visible_customer(db, request, editor, customer_id)
    keyring = Keyring()
    sealer = keyring.sealer(customer)
    people = chosen_people(db, customer.id, body.audience, body.people)
    fields = renewal_fields(db, sealer, customer, body, {})
    renewal = CustomerRenewal(customer_id=customer.id, renews_on=body.renews_on,
                              warn_days=body.warn_days, audience=body.audience, sealed=b"")
    db.add(renewal)
    db.flush()
    renewal.sealed = sealer.seal("renewal", renewal.id, fields)
    _set_people(db, CustomerRenewalPerson, "renewal_id", renewal.id, people)
    _log(db, request, editor, "customer.renewal_added", customer.id, {"renewal": renewal.id})
    db.commit()
    return _detail(db, editor, keyring, customer, "full")


@router.put("/{customer_id}/renewals/{renewal_id}")
def change_renewal(customer_id: int, renewal_id: int, body: RenewalIn, request: Request,
                   editor: Editor, db: DB) -> CustomerDetail:
    """Change what a renewal is, when it renews and who is warned; not the decision."""
    customer, _ = visible_customer(db, request, editor, customer_id)
    renewal = _renewal(db, customer, renewal_id)
    keyring = Keyring()
    sealer = keyring.sealer(customer)
    people = chosen_people(db, customer.id, body.audience, body.people)
    before = sealer.open("renewal", renewal.id, renewal.sealed)
    fields = renewal_fields(db, sealer, customer, body, before)
    changes: dict[str, object] = {"renewal": renewal.id}
    if renewal.renews_on != body.renews_on:
        changes["renews_on"] = [renewal.renews_on.isoformat(), body.renews_on.isoformat()]
    renewal.renews_on, renewal.warn_days, renewal.audience = (
        body.renews_on, body.warn_days, body.audience)
    renewal.sealed = sealer.seal("renewal", renewal.id, fields)
    _set_people(db, CustomerRenewalPerson, "renewal_id", renewal.id, people)
    _log(db, request, editor, "customer.renewal_changed", customer.id, changes)
    db.commit()
    return _detail(db, editor, keyring, customer, "full")


@router.post("/{customer_id}/renewals/{renewal_id}/decision")
def decide_renewal(customer_id: int, renewal_id: int, body: DecisionIn, request: Request,
                   manager: Manager, db: DB) -> CustomerDetail:
    """Record the decision. Won't be renewed needs the reason, and what must be done
    before it runs out becomes a task."""
    customer, _ = visible_customer(db, request, manager, customer_id)
    renewal = _renewal(db, customer, renewal_id)
    if body.decision == "declined" and not body.reason:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                            "Say why it won't be renewed.")
    keyring = Keyring()
    sealer = keyring.sealer(customer)
    sealed = sealer.open("renewal", renewal.id, renewal.sealed)
    declined = body.decision == "declined"
    sealed["reason"] = body.reason if declined else ""
    sealed["fallback"] = body.fallback.strip() if declined else ""
    details: dict[str, object] = {"renewal": renewal.id,
                                  "decision": [renewal.decision, body.decision]}
    renewal.decision = body.decision
    renewal.sealed = sealer.seal("renewal", renewal.id, sealed)
    what = str(sealed.get("what", ""))
    if declined:
        _note(db, sealer, customer, manager,
              f"{what}: won't be renewed, because {REASONS[body.reason]}.", sealed)
        if sealed["fallback"]:
            due = body.fallback_due or renewal.renews_on - timedelta(days=2)
            task = _new_task(db, sealer, customer, TaskIn(
                title=sealed["fallback"], due_on=due, audience="technicians",
                notes=f"{what} runs out on {renewal.renews_on.isoformat()} and won't be renewed.",
                service_id=sealed.get("service_id"), system_id=sealed.get("system_id"),
            ), manager.user_id, renewal.id)
            details["task"] = task.id
    elif body.decision == "approved":
        _note(db, sealer, customer, manager, f"{what}: renewal approved.", sealed)
    _log(db, request, manager, "customer.renewal_decided", customer.id, details)
    db.commit()
    return _detail(db, manager, keyring, customer, "full")


@router.post("/{customer_id}/renewals/{renewal_id}/renewed")
def mark_renewed(customer_id: int, renewal_id: int, body: Renewed, request: Request,
                 editor: Editor, db: DB) -> CustomerDetail:
    """It's been renewed. One that renews again moves to its next date, undecided;
    a one-off stays, as Renewed."""
    customer, _ = visible_customer(db, request, editor, customer_id)
    renewal = _renewal(db, customer, renewal_id)
    if renewal.decision == "renewed":
        raise HTTPException(status.HTTP_409_CONFLICT, "That's already marked as renewed.")
    keyring = Keyring()
    sealer = keyring.sealer(customer)
    sealed = sealer.open("renewal", renewal.id, renewal.sealed)
    every = Every.model_validate(sealed["every"]) if sealed.get("every") else None
    if body.next_on is not None and body.next_on <= renewal.renews_on:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                            "The next renewal is after this one.")
    next_on = body.next_on or (add_interval(renewal.renews_on, every) if every else None)
    what, note = str(sealed.get("what", "")), body.note.strip()
    text = f"{what}: renewed" + (f", next on {next_on.isoformat()}" if next_on else "")
    _note(db, sealer, customer, editor, f"{text}. {note}".strip(), sealed)
    details: dict[str, object] = {"renewal": renewal.id}
    if next_on:
        details["next_on"] = next_on.isoformat()
        renewal.renews_on, renewal.decision = next_on, ""
    else:
        renewal.decision = "renewed"
    sealed["reason"] = sealed["fallback"] = ""
    renewal.sealed = sealer.seal("renewal", renewal.id, sealed)
    _log(db, request, editor, "customer.renewal_renewed", customer.id, details)
    db.commit()
    return _detail(db, editor, keyring, customer, "full")


@router.delete("/{customer_id}/renewals/{renewal_id}")
def remove_renewal(customer_id: int, renewal_id: int, request: Request, manager: Manager,
                   db: DB) -> CustomerDetail:
    customer, _ = visible_customer(db, request, manager, customer_id)
    db.delete(_renewal(db, customer, renewal_id))
    _log(db, request, manager, "customer.renewal_removed", customer.id, {"renewal": renewal_id})
    db.commit()
    return _detail(db, manager, Keyring(), customer, "full")
