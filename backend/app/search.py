"""Global search: the phone rings, and the technician types what they have.

A company name, a CVR number, a contact's name, a phone number, an email domain,
a case number or a system's name finds the customer. Everything searched is
sealed, so the search opens the records of the customers the searcher may see
and matches them in memory (docs/architecture.md, "Search"). Nothing is stored
for it, and what was typed is never logged: it would put a customer's name in
the audit log.

Someone who sees a customer in full searches all of that. An Auditor, who sees
that customers exist and nothing more, finds them by name only.
"""

from __future__ import annotations

import re
from typing import Annotated, Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import select

from app.auth.dependencies import DB, FullSession
from app.customer_routes import companies_of, contacts_of, sites_of, town_of
from app.customer_services import services_of
from app.customers import (
    Customer,
    Keyring,
    Status,
    assigned_customer_ids,
    is_limited,
    level_for,
    sights,
)
from app.roles import roles_of
from app.systems import systems_of

router = APIRouter(prefix="/search")

HITS_SHOWN = 20
Kind = Literal["customer", "company", "contact", "site", "system", "case"]
# The customer's page that shows what was found.
Page = Literal["overview", "contacts", "systems", "services"]


class Hit(BaseModel):
    kind: Kind
    customer_id: int
    customer: str
    # Active, departing or former; none for someone who sees only that it exists.
    status: Status | None = None
    # What matched (the contact, the system, the case number) and a line about it.
    title: str
    detail: str = ""
    page: Page = "overview"
    # The service or system to open on that page.
    record_id: int | None = None


class Found(BaseModel):
    hits: list[Hit]
    # There were more than are shown: type more to narrow it down.
    more: bool = False


def _plain(text: str | None) -> str:
    return " ".join((text or "").casefold().split())


def _tight(text: str | None) -> str:
    """Without the spaces and punctuation numbers are written with."""
    return re.sub(r"[\s\-().]", "", (text or "").casefold())


def _digits(text: str | None) -> str:
    return re.sub(r"\D", "", text or "")


def cvr_groups(cvr: str | None) -> str:
    """ "12 34 56 78": a CVR number in the groups people read it in."""
    return re.sub(r"(\d{2})(?=\d)", r"\1 ", cvr or "")


class Needle:
    """What was typed, in the forms it's compared in."""

    def __init__(self, typed: str) -> None:
        self.words = _plain(typed)
        self.tight = _tight(typed)
        # A phone number is found whatever country code or spacing it's written with.
        numeric = re.fullmatch(r"[\d\s+\-().]+", typed.strip()) is not None
        self.digits = _digits(typed) if numeric and len(_digits(typed)) >= 3 else ""

    def text(self, value: str | None) -> int | None:
        """How well some words match: 0 from the start, 1 from a word's start, 2 anywhere."""
        plain = _plain(value)
        if not self.words or self.words not in plain:
            return None
        if plain.startswith(self.words):
            return 0
        return 1 if f" {self.words}" in plain else 2

    def number(self, value: str | None) -> bool:
        """A CVR number, phone number or case number, however it's spaced."""
        if not value:
            return False
        return bool(self.tight and self.tight in _tight(value)) or bool(
            self.digits and self.digits in _digits(value))


def _joined(*parts: str | None) -> str:
    return " · ".join(part for part in parts if part)


def _full(db: DB, keyring: Keyring, customer: Customer, name: str, needle: Needle
          ) -> list[tuple[int, Hit]]:
    """A customer's matches among everything about it, each with its rank."""
    sealer = keyring.sealer(customer)
    details = keyring.details(customer)
    found: list[tuple[int, Hit]] = []

    def hit(rank: int, kind: Kind, title: str, detail: str = "", page: Page = "overview",
            record_id: int | None = None) -> None:
        found.append((rank, Hit(kind=kind, customer_id=customer.id, customer=name,
                                status=customer.status,  # type: ignore[arg-type]
                                title=title, detail=detail, page=page, record_id=record_id)))

    about = _joined(details["cvr"] and f"CVR {cvr_groups(details['cvr'])}",
                    town_of(details["address"] or ""))
    by_name = needle.text(name)
    if by_name is not None:
        hit(by_name, "customer", name, about)
    elif needle.number(details["cvr"]):
        hit(1, "customer", name, about)

    for company in companies_of(db, sealer, customer.id):
        if needle.text(company.name) is not None or needle.number(company.cvr):
            hit(3, "company", company.name,
                _joined("Group company", company.cvr and f"CVR {cvr_groups(company.cvr)}"))
    for contact in contacts_of(db, sealer, customer.id):
        by_contact = needle.text(contact.name)
        if by_contact is not None:
            rank = 2 + by_contact
        elif needle.text(contact.email) is not None or (
                needle.tight and needle.tight in _tight(contact.email)):
            rank = 4
        elif needle.number(contact.phone):
            rank = 4
        else:
            continue
        hit(rank, "contact", contact.name, _joined(contact.role, contact.email, contact.phone),
            "contacts")
    for service in services_of(db, sealer, customer.id):
        if needle.number(service.case_number):
            exact = needle.tight == _tight(service.case_number)
            hit(1 if exact else 2, "case", service.case_number,
                _joined("Log time on", service.name), "services", service.id)
            continue
        earlier = next((c for c in service.case_history if needle.number(c.number)), None)
        if earlier:
            hit(5, "case", earlier.number,
                _joined("Earlier case number", service.name,
                        f"until {earlier.until.isoformat()}"), "services", service.id)
    for system in systems_of(db, sealer, customer.id):
        if (needle.text(system.name) is not None or needle.text(system.hostname) is not None
                or (needle.tight and needle.tight in _tight(system.ip))):
            hit(5, "system", system.name, _joined(system.role, system.hostname, system.ip),
                "systems", system.id)
    for site in sites_of(db, sealer, customer.id):
        if needle.text(site.name) is not None or needle.text(site.address) is not None:
            hit(6, "site", site.name, " ".join(site.address.split()), "contacts")
    return found


@router.get("")
def search(record: FullSession, db: DB,
           q: Annotated[str, Query(min_length=2, max_length=100)]) -> Found:
    needle = Needle(q)
    if len(needle.words) < 2:
        return Found(hits=[])
    sight = sights(roles_of(db, record.user_id), is_limited(db, record.user_id))
    assigned = assigned_customer_ids(db, record.user_id)
    keyring = Keyring()
    found: list[tuple[int, Hit]] = []
    for customer in db.scalars(select(Customer)):
        level = level_for(sight, customer.id in assigned)
        if level is None:
            continue
        name = keyring.name(customer)
        if level == "full":
            found += _full(db, keyring, customer, name, needle)
        elif (rank := needle.text(name)) is not None:
            found.append((rank, Hit(kind="customer", customer_id=customer.id, customer=name,
                                    title=name)))
    found.sort(key=lambda pair: (pair[0], pair[1].customer.casefold(), pair[1].title.casefold()))
    return Found(hits=[hit for _, hit in found[:HITS_SHOWN]], more=len(found) > HITS_SHOWN)
