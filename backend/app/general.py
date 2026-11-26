"""The team's general settings: how Þing behaves for everyone, set in the admin panel.

- How far ahead what's coming up reaches (renewals, recurring work, notice days):
  three months to three years. It's the outer bound: what's nearer always shows,
  what's further stays on its own page without a warning. Managers set this one
  too, since the warnings are theirs.
- Whether work ticked off from a task or a renewal is marked Covered or Billable,
  like work logged by hand.
- Whether a new customer's overview shows the Getting started steps.
- The country code offered first for a phone number.

None of it is secret, and the pages need it, so everyone signed in reads it.
Every change is in the audit log.
"""

from __future__ import annotations

import calendar
import json
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import audit
from app.auth.dependencies import DB, FullSession, client_ip, require
from app.auth.sessions import UserSession
from app.policy import Setting
from app.roles import Capability

GENERAL_KEY = "general"
# What the admin panel offers; anything from three months to three years is taken.
AHEAD_MONTHS = (3, 6, 12, 18, 24, 36)

router = APIRouter(prefix="/general")
Admin = Annotated[UserSession, Depends(require(Capability.ADMINISTER))]
Manager = Annotated[UserSession, Depends(require(Capability.MANAGE_CUSTOMERS))]


class Warnings(BaseModel):
    """What the Managers set too."""

    # How far ahead what's coming up is shown and warned about, in months.
    warn_ahead_months: int = Field(default=12, ge=3, le=36)


class General(Warnings):
    # Work ticked off from a task or a renewal is marked Covered or Billable.
    cover_ticked_off_work: bool = True
    # A new customer's overview shows the Getting started steps.
    getting_started: bool = True
    # The country code offered first for a phone number: "+45".
    phone_country_code: str = Field(default="+45", pattern=r"^\+[1-9][0-9]{0,3}$")


def general(db: Session) -> General:
    stored = db.get(Setting, GENERAL_KEY)
    known = General.model_fields.keys()
    saved = json.loads(stored.value) if stored else {}
    return General(**{name: value for name, value in saved.items() if name in known})


def ahead(db: Session, today: date) -> date:
    """The last day that counts as coming up."""
    months = today.month - 1 + general(db).warn_ahead_months
    year, month = today.year + months // 12, months % 12 + 1
    return date(year, month, min(today.day, calendar.monthrange(year, month)[1]))


def _save(db: Session, request: Request, record: UserSession, after: General) -> General:
    before = general(db)
    changes = {name: [getattr(before, name), getattr(after, name)]
               for name in General.model_fields if getattr(before, name) != getattr(after, name)}
    if changes:
        db.merge(Setting(key=GENERAL_KEY, value=json.dumps(after.model_dump())))
        audit.append(db, "admin.general_changed", actor_id=record.user.id,
                     actor_name=record.user.username, target_type=None, target_id=None,
                     ip=client_ip(request), details={"changes": changes})
        db.commit()
    return after


@router.get("")
def read_general(_: FullSession, db: DB) -> General:
    return general(db)


@router.put("")
def change_general(body: General, request: Request, admin: Admin, db: DB) -> General:
    return _save(db, request, admin, body)


@router.put("/warnings")
def change_warnings(body: Warnings, request: Request, manager: Manager, db: DB) -> General:
    """How far ahead warnings reach: the Managers', as well as the Administrators'."""
    return _save(db, request, manager,
                 general(db).model_copy(update={"warn_ahead_months": body.warn_ahead_months}))
