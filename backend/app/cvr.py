"""CVR lookup: a company's name and address from its CVR number, through cvrapi.dk.

Off until an Administrator switches it on (Admin -> Integrations): it's Þing's
one call out to a third party about customers. Only the CVR number or company
name typed is sent, and only when someone asks for a lookup; Þing never looks a
customer up again by itself.

cvrapi.dk's terms (https://cvrapi.dk/terms and /documentation): 50 free
lookups a day per organisation, never got round by changing IP address or
User-Agent, and a User-Agent naming the organisation, the project and a
contact person ("Company - Project - Name email"), which the Administrator gives
when switching it on. Answers are kept for a day, so the same number doesn't
use up another lookup.
"""

from __future__ import annotations

import re
import time
import unicodedata
from typing import Annotated, Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit
from app.auth.dependencies import DB, FullSession, client_ip, require, require_step_up
from app.auth.sessions import UserSession
from app.policy import Setting
from app.roles import Capability
from app.setup import company_name

SETTING = "integrations/cvr"
API = "https://cvrapi.dk/api"
TIMEOUT_SECONDS = 10
CACHE_SECONDS = 24 * 3600

router = APIRouter()
Editor = Annotated[UserSession, Depends(require(Capability.EDIT_CUSTOMERS))]
Admin = Annotated[UserSession, Depends(require(Capability.ADMINISTER))]


class CvrSettings(BaseModel):
    enabled: bool = False
    # The contact person in the User-Agent cvrapi.dk asks for: a name and a work
    # email or phone, such as "Henrik Dahl it@nordlys.example".
    contact: str = Field(default="", max_length=150, pattern=r"^[^\r\n]*$")


class Company(BaseModel):
    cvr: str
    name: str
    # Street, then postcode and town on a line of their own.
    address: str


class LookupError_(Exception):
    """A lookup that didn't give a company; the message is fit to show."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code


def load_settings(db: Session) -> CvrSettings:
    stored = db.scalar(select(Setting.value).where(Setting.key == SETTING))
    return CvrSettings.model_validate_json(stored) if stored else CvrSettings()


def save_settings(db: Session, settings: CvrSettings) -> None:
    db.merge(Setting(key=SETTING, value=settings.model_dump_json()))


_LETTERS: dict[str, str | int | None] = {
    "æ": "ae", "Æ": "Ae", "ø": "oe", "Ø": "Oe", "å": "aa", "Å": "Aa", "þ": "th", "Þ": "Th"}
_SPELT = str.maketrans(_LETTERS)


def _ascii(text: str) -> str:
    """HTTP headers are ASCII: Danish letters spelt out, other accents dropped."""
    spelt = text.translate(_SPELT)
    plain = unicodedata.normalize("NFKD", spelt).encode("ascii", "ignore").decode()
    return " ".join(plain.split())


def user_agent(company: str | None, contact: str) -> str:
    """cvrapi.dk's template: "Company - Project - Contact", in ASCII (so "Ting", not
    "Þing")."""
    return _ascii(f"{company or 'Unnamed company'} - Ting CRM - {contact}")


_cache: dict[str, tuple[float, Company]] = {}

# cvrapi.dk's error codes, and what to tell the person who asked.
_ERRORS = {
    "NOT_FOUND": (status.HTTP_404_NOT_FOUND, "No company with that CVR number or name."),
    "INVALID_VAT": (status.HTTP_422_UNPROCESSABLE_CONTENT, "That isn't a CVR number."),
    "QUOTA_EXCEEDED": (status.HTTP_429_TOO_MANY_REQUESTS,
                       "Today's 50 free CVR lookups are used up. Type the details in."),
}


def _client(agent: str) -> httpx.Client:
    return httpx.Client(timeout=TIMEOUT_SECONDS, headers={"User-Agent": agent})


def lookup(search: str, agent: str, now: float | None = None) -> Company:
    """The company with this CVR number (8 digits) or name."""
    now = time.monotonic() if now is None else now
    key = search.casefold()
    if (hit := _cache.get(key)) and now - hit[0] < CACHE_SECONDS:
        return hit[1]
    digits = search.replace(" ", "")
    params = {"country": "dk", **({"vat": digits} if re.fullmatch(r"\d{8}", digits)
                                   else {"name": search})}
    try:
        with _client(agent) as client:
            response = client.get(API, params=params)
        found: dict[str, Any] = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise LookupError_(status.HTTP_502_BAD_GATEWAY,
                           "The CVR register couldn't be reached. Type the details in.") from exc
    if "error" in found or "vat" not in found:
        code, message = _ERRORS.get(str(found.get("error")), (
            status.HTTP_502_BAD_GATEWAY, "The CVR register couldn't answer. Type the details in."))
        raise LookupError_(code, message)
    town = " ".join(str(part) for part in (found.get("zipcode"), found.get("city")) if part)
    company = Company(
        cvr=str(found["vat"]), name=str(found.get("name") or ""),
        address="\n".join(part for part in (str(found.get("address") or ""), town) if part),
    )
    _cache[key] = (now, company)
    return company


# Routes


class CvrStatus(BaseModel):
    enabled: bool


@router.get("/cvr/status")
def cvr_status(_: FullSession, db: DB) -> CvrStatus:
    """Whether the forms offer a lookup."""
    return CvrStatus(enabled=load_settings(db).enabled)


@router.get("/cvr")
def cvr_lookup(request: Request, record: Editor, db: DB,
               search: Annotated[str, Query(min_length=2, max_length=200)]) -> Company:
    settings = load_settings(db)
    if not settings.enabled:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "CVR lookup is off. An Administrator switches it on in Admin.")
    try:
        company = lookup(search.strip(), user_agent(company_name(db), settings.contact))
    except LookupError_ as exc:
        _log(db, request, record, "cvr.lookup", {"search": search.strip(), "found": False})
        db.commit()
        raise HTTPException(exc.status_code, str(exc)) from exc
    _log(db, request, record, "cvr.lookup", {"search": search.strip(), "found": company.cvr})
    db.commit()
    return company


def _log(db: Session, request: Request, record: UserSession, action: str,
         details: dict[str, object]) -> None:
    audit.append(db, action, actor_id=record.user.id, actor_name=record.user.username,
                 ip=client_ip(request), details=details)


@router.get("/admin/integrations/cvr")
def get_cvr_settings(_: Admin, db: DB) -> CvrSettings:
    return load_settings(db)


@router.put("/admin/integrations/cvr")
def put_cvr_settings(body: CvrSettings, request: Request, admin: Admin, db: DB) -> CvrSettings:
    if body.enabled and not body.contact.strip():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                            "Give a contact person: cvrapi.dk asks for one.")
    current = load_settings(db)
    if body.enabled and not current.enabled:
        # Þing starts calling a third party: the person switching it on confirms it's them.
        require_step_up(admin, "Confirm it's you to switch on the CVR lookup.")
    settings = CvrSettings(enabled=body.enabled, contact=body.contact.strip())
    save_settings(db, settings)
    _log(db, request, admin, "admin.cvr_lookup_changed", {"enabled": settings.enabled})
    db.commit()
    return settings
