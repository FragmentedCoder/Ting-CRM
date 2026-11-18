"""The customers API: customers, their sites and contacts, who's assigned, the logo.

Creating customers, choosing who's assigned, retention and the logo are for
Administrators and Managers (MANAGE_CUSTOMERS); deleting one is for Administrators
only (DELETE_CUSTOMERS).
Technicians change the details, sites and contacts of the customers they're
assigned to (EDIT_CUSTOMERS). Everyone sees what app/customers.py allows. A
customer someone may not see answers 404, the same as one that doesn't exist,
and the refusal is logged.
Everything about a customer is sealed with its key and opened per request, only
for those allowed to see it; the audit log names customers by ID only.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import date, datetime
from typing import Annotated, Any, Literal, Self

from fastapi import APIRouter, Body, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import audit, clock
from app.agreements import (
    AgreementIn,
    AgreementOut,
    CustomerAgreement,
    agreements_of,
    coverage,
)
from app.agreements import sealed_fields as agreement_fields
from app.auth.dependencies import DB, FullSession, client_ip, require, require_step_up
from app.auth.sessions import UserSession
from app.customer_services import (
    CustomerService,
    CustomerServiceIn,
    CustomerServiceOut,
    services_of,
)
from app.customer_services import sealed_fields as service_fields
from app.customers import (
    PINS_PER_CUSTOMER,
    Customer,
    CustomerAssignment,
    CustomerCompany,
    CustomerContact,
    CustomerPin,
    CustomerSite,
    CustomerSystem,
    Keyring,
    Sealer,
    Status,
    Visibility,
    assigned_customer_ids,
    is_limited,
    level_for,
    may_delete,
    may_edit,
    may_manage,
    sights,
    visibility,
)
from app.images import (
    IMAGE_HEADERS,
    LOGO_SIZE,
    ImageRejected,
    clean_image,
    image_version,
    load_image,
    remove_image,
    store_image,
)
from app.planning import RenewalOut, TaskOut, Who, colleagues, open_tasks, renewals_of
from app.roles import Capability, Role, UserRole, can, roles_of
from app.services import StandardService
from app.systems import SystemIn, SystemOut, sealed_fields, systems_of, would_loop
from app.users import User
from app.worklog import LogEntryOut, entries_of

router = APIRouter(prefix="/customers")

Manager = Annotated[UserSession, Depends(require(Capability.MANAGE_CUSTOMERS))]
Editor = Annotated[UserSession, Depends(require(Capability.EDIT_CUSTOMERS))]
Deleter = Annotated[UserSession, Depends(require(Capability.DELETE_CUSTOMERS))]
Agreer = Annotated[UserSession, Depends(require(Capability.MANAGE_AGREEMENTS))]

NOT_FOUND = "That customer doesn't exist."
ORDER: dict[Visibility, int] = {"metadata": 1, "full": 2}


SiteKind = Literal["main", "office", "production", "warehouse", "group_company", "other"]
ContactRole = Literal["primary", "technical", "billing", "decision_maker", "security"]
Channel = Literal["", "phone", "email"]


class SiteIn(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    kind: SiteKind = "other"
    address: str = Field(default="", max_length=500)
    opening_hours: str = Field(default="", max_length=300)
    access: str = Field(default="", max_length=500)
    parking: str = Field(default="", max_length=300)
    note: str = Field(default="", max_length=1000)
    # The site's own contact: one of the customer's contacts (it may be the
    # contact of another site too).
    contact_id: int | None = None


class SiteOut(SiteIn):
    id: int


class ContactIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    # The role line on the card: their title at the customer ("CEO", "IT coordinator").
    role: str = Field(default="", max_length=150)
    email: str = Field(default="", max_length=254, pattern=r"^([^@\s]+@[^@\s]+)?$")
    phone: str = Field(default="", max_length=50, pattern=r"^[0-9+()\-. ]*$")
    # What they are to us: who decides, who's technical, billing, the security contact.
    roles: list[ContactRole] = Field(default=[], max_length=5)
    # The site they're at; none for the whole company.
    site_id: int | None = None
    may_contact: bool = True
    may_contact_note: str = Field(default="", max_length=200)
    preferred_channel: Channel = ""

    @field_validator("roles")
    @classmethod
    def _distinct(cls, roles: list[ContactRole]) -> list[ContactRole]:
        return sorted(set(roles))


class ContactOut(ContactIn):
    id: int


class PinIn(BaseModel):
    # One line: short enough to read at a glance, never wrapped.
    text: str = Field(min_length=1, max_length=120, pattern=r"^[^\r\n]*$")
    # A hard rule (red) or a caution (yellow).
    severity: Literal["critical", "caution"] = "caution"


class PinOut(PinIn):
    id: int
    # "Henrik Dahl, Manager"; None once that person is gone.
    pinned_by: str | None
    pinned_at: datetime


def _cvr(value: str | None) -> str | None:
    """A Danish CVR number: 8 digits, spaces allowed while typing. Empty for none."""
    if value is None:
        return None
    digits = value.replace(" ", "")
    if not digits:
        return None
    if not (len(digits) == 8 and digits.isdigit()):
        raise ValueError("A CVR number has 8 digits.")
    return digits


def _status_day(status: Status | None, day: date | None) -> None:
    """A departing customer needs the day it leaves, a former one the day it left;
    an active one has neither."""
    if status in ("departing", "former") and day is None:
        raise ValueError("Give the day the customer leaves or left.")
    if status == "active" and day is not None:
        raise ValueError("An active customer has no leaving day.")


class CustomerIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    cvr: str | None = None
    address: str = Field(default="", max_length=1000)
    # Months the records are kept once it's a former customer.
    retention_months: int = Field(default=12, ge=1, le=120)
    status: Status = "active"
    status_date: date | None = None

    _check_cvr = field_validator("cvr")(_cvr)

    @model_validator(mode="after")
    def _check_status(self) -> Self:
        _status_day(self.status, self.status_date)
        return self


class CustomerUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    cvr: str | None = None
    address: str | None = Field(default=None, max_length=1000)
    # Only those who manage customers change these.
    retention_months: int | None = Field(default=None, ge=1, le=120)
    # Given together: the status and its day (none for an active customer).
    status: Status | None = None
    status_date: date | None = None

    _check_cvr = field_validator("cvr")(_cvr)

    @model_validator(mode="after")
    def _check_status(self) -> Self:
        if self.status is not None:
            _status_day(self.status, self.status_date)
        elif "status_date" in self.model_fields_set:
            raise ValueError("Give the status with its day.")
        return self


class CompanyIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    cvr: str | None = None
    address: str = Field(default="", max_length=1000)

    _check_cvr = field_validator("cvr")(_cvr)


class CompanyOut(CompanyIn):
    id: int


class Person(BaseModel):
    id: int
    username: str
    display_name: str
    roles: list[Role]


class CustomerSummary(BaseModel):
    id: int
    name: str
    visibility: Visibility
    # Only with full sight.
    cvr: str | None = None
    status: Status | None = None
    status_date: date | None = None
    # The town from the address's postcode line ("8000 Aarhus C" gives "Aarhus C").
    town: str | None = None
    people: int | None = None
    # Who usually works with it (its assigned technicians), and whether you do.
    worked_on_by: list[str] | None = None
    mine: bool | None = None
    logo_url: str | None = None


class CustomerDetail(CustomerSummary):
    # Only with full sight.
    address: str | None = None
    retention_months: int | None = None
    created_at: datetime | None = None
    sites: list[SiteOut] | None = None
    contacts: list[ContactOut] | None = None
    # The other companies in the group (the customer itself is the main one).
    companies: list[CompanyOut] | None = None
    systems: list[SystemOut] | None = None
    services: list[CustomerServiceOut] | None = None
    agreements: list[AgreementOut] | None = None
    # The newest work log entries, for the overview.
    latest_work: list[LogEntryOut] | None = None
    # What's coming up: the tasks not yet done, and the renewals.
    tasks: list[TaskOut] | None = None
    renewals: list[RenewalOut] | None = None
    # Who a task or renewal can name: everyone who sees this customer in full.
    colleagues: list[Who] | None = None
    pins: list[PinOut] | None = None
    assigned: list[Person] | None = None
    may_manage: bool = False
    # Create and change agreements (Managers and Administrators).
    may_manage_agreements: bool = False
    may_edit: bool = False
    may_delete: bool = False
    # For an Administrator or Manager choosing who's assigned: everyone who may be.
    assignable: list[Person] | None = None


class Assignments(BaseModel):
    """Who works with the customer: the technicians assigned to it."""

    people: list[int] = Field(default=[], max_length=500)


class DeleteRequest(BaseModel):
    # Typed by the person deleting, so a slip of the mouse deletes nothing.
    confirm_name: str


def _log(
    db: Session, request: Request, record: UserSession, action: str, customer_id: int,
    details: dict[str, object] | None = None,
) -> None:
    audit.append(
        db, action, actor_id=record.user.id, actor_name=record.user.username,
        target_type="customer", target_id=str(customer_id), ip=client_ip(request),
        details=details,
    )


def logo_key(customer_id: int) -> str:
    return f"customer/{customer_id}/logo"


def _logo_url(db: Session, customer_id: int) -> str | None:
    version = image_version(db, logo_key(customer_id))
    return f"/api/customers/{customer_id}/logo?v={version}" if version else None


def visible_customer(
    db: Session, request: Request, record: UserSession, customer_id: int,
    need: Visibility = "full",
) -> tuple[Customer, Visibility]:
    """The customer, if this person may see at least `need` of it; else 404."""
    customer = db.get(Customer, customer_id)
    level = (
        visibility(db, record.user_id, roles_of(db, record.user_id), customer_id)
        if customer else None
    )
    if customer is None or level is None or ORDER[level] < ORDER[need]:
        if customer is not None:
            _log(db, request, record, "customer.access_denied", customer_id, {"needed": need})
            db.commit()
        raise HTTPException(status.HTTP_404_NOT_FOUND, NOT_FOUND)
    return customer, level


class Team:
    """Who is assigned to which customer, and their names: read once per request."""

    def __init__(self, db: Session) -> None:
        self.held: dict[int, list[int]] = {}
        for customer_id, user_id in db.execute(
                select(CustomerAssignment.customer_id, CustomerAssignment.user_id)):
            self.held.setdefault(customer_id, []).append(user_id)
        ids = {user_id for people in self.held.values() for user_id in people}
        # A Result has keys(), so dict() would take it for a mapping: unpack the rows.
        self.names = {user_id: name for user_id, name in db.execute(
            select(User.id, User.display_name).where(User.id.in_(ids)))}

    def of(self, customer_id: int) -> list[int]:
        return self.held.get(customer_id, [])


def town_of(address: str) -> str | None:
    """The town after a Danish postcode, on its own line or after a comma:
    "8000 Aarhus C" and "Fjordvej 1, 8000 Aarhus C" both give "Aarhus C"."""
    for line in reversed(address.splitlines()):
        if match := re.search(r"(?:^|,)\s*(?:DK-?)?\d{4}\s+([^,]+?)\s*$", line):
            return match.group(1)
    return None


def _summary(db: Session, keyring: Keyring, customer: Customer, level: Visibility,
             team: Team, me: int) -> dict[str, Any]:
    details = keyring.details(customer)
    fields: dict[str, Any] = {"id": customer.id, "name": details["name"], "visibility": level}
    if level == "full":
        people = team.of(customer.id)
        fields |= {"cvr": details["cvr"], "logo_url": _logo_url(db, customer.id),
                   "status": customer.status, "status_date": customer.status_date,
                   "town": town_of(details["address"] or ""),
                   "people": len(people), "mine": me in people,
                   "worked_on_by": sorted((team.names[u] for u in people), key=str.casefold)}
    return fields


def _people(db: Session, user_ids: list[int]) -> list[Person]:
    if not user_ids:
        return []
    users = db.scalars(select(User).where(User.id.in_(user_ids)).order_by(User.display_name))
    return [Person(id=u.id, username=u.username, display_name=u.display_name,
                   roles=sorted(roles_of(db, u.id))) for u in users]


def _assignable_ids(db: Session) -> list[int]:
    """Active technicians: the people assignments are for. Administrators and
    Managers see every customer without one."""
    return list(db.scalars(
        select(UserRole.user_id).join(User, User.id == UserRole.user_id)
        .where(UserRole.role == Role.TECHNICIAN.value, User.is_active)
        .distinct()
    ))


def sites_of(db: Session, sealer: Sealer, customer_id: int) -> list[SiteOut]:
    sites = db.scalars(select(CustomerSite).where(CustomerSite.customer_id == customer_id))
    found = [SiteOut(id=s.id, **sealer.open("site", s.id, s.sealed)) for s in sites]
    return sorted(found, key=lambda s: s.name.casefold())


def contacts_of(db: Session, sealer: Sealer, customer_id: int) -> list[ContactOut]:
    contacts = db.scalars(
        select(CustomerContact).where(CustomerContact.customer_id == customer_id)
    )
    found = [ContactOut(id=c.id, **sealer.open("contact", c.id, c.sealed)) for c in contacts]
    return sorted(found, key=lambda c: c.name.casefold())


def companies_of(db: Session, sealer: Sealer, customer_id: int) -> list[CompanyOut]:
    rows = db.scalars(select(CustomerCompany).where(CustomerCompany.customer_id == customer_id))
    found = [CompanyOut(id=c.id, **sealer.open("company", c.id, c.sealed)) for c in rows]
    return sorted(found, key=lambda c: c.name.casefold())


def _pinner(db: Session, user_id: int | None) -> str | None:
    """Who pinned it, with the role that let them: "Henrik Dahl, Manager"."""
    user = db.get(User, user_id) if user_id is not None else None
    if user is None:
        return None
    roles = roles_of(db, user.id)
    role = "Manager" if Role.MANAGER in roles else "Administrator"
    return f"{user.display_name}, {role}"


def pins_of(db: Session, sealer: Sealer, customer_id: int) -> list[PinOut]:
    pins = db.scalars(select(CustomerPin).where(CustomerPin.customer_id == customer_id)
                      .order_by(CustomerPin.id))
    found = [PinOut(id=pin.id, pinned_by=_pinner(db, pin.pinned_by), pinned_at=pin.pinned_at,
                    **sealer.open("pin", pin.id, pin.sealed)) for pin in pins]
    # Hard rules first, then cautions, each in the order they were pinned.
    return sorted(found, key=lambda pin: pin.severity != "critical")


def _detail(db: Session, record: UserSession, keyring: Keyring, customer: Customer,
            level: Visibility) -> CustomerDetail:
    summary = _summary(db, keyring, customer, level, Team(db), record.user_id)
    if level != "full":
        return CustomerDetail(**summary)
    roles = roles_of(db, record.user_id)
    sealer = keyring.sealer(customer)
    held = db.scalars(select(CustomerAssignment.user_id)
                      .where(CustomerAssignment.customer_id == customer.id))
    manage = may_manage(roles)
    agreements = agreements_of(db, sealer, customer.id)
    covered = coverage(agreements)
    services = services_of(db, sealer, customer.id)
    for service in services:
        service.agreement = covered.get(service.id)
    return CustomerDetail(
        **summary,
        address=keyring.details(customer)["address"],
        retention_months=customer.retention_months,
        created_at=customer.created_at,
        sites=sites_of(db, sealer, customer.id),
        contacts=contacts_of(db, sealer, customer.id),
        companies=companies_of(db, sealer, customer.id),
        systems=systems_of(db, sealer, customer.id),
        services=services,
        agreements=agreements,
        latest_work=entries_of(db, sealer, customer.id, viewer_id=record.user_id,
                               manages=manage, limit=3),
        tasks=open_tasks(db, sealer, customer.id, record.user_id, manage),
        renewals=renewals_of(db, sealer, customer.id),
        colleagues=colleagues(db, customer.id),
        pins=pins_of(db, sealer, customer.id),
        assigned=_people(db, list(held)),
        may_manage=manage,
        may_manage_agreements=can(roles, Capability.MANAGE_AGREEMENTS),
        may_edit=may_edit(roles),
        may_delete=may_delete(roles),
        assignable=_people(db, _assignable_ids(db)) if manage else None,
    )


# Customers


@router.get("")
def list_customers(record: FullSession, db: DB, q: str = "") -> list[CustomerSummary]:
    """The customers this person sees, by name; q searches names and CVR numbers.
    Names are sealed, so the search runs here, over the opened ones."""
    sight = sights(roles_of(db, record.user_id), is_limited(db, record.user_id))
    assigned = assigned_customer_ids(db, record.user_id)
    team = Team(db)
    keyring = Keyring()
    needle = q.strip().casefold().replace(" ", "")
    found = []
    for customer in db.scalars(select(Customer)):
        level = level_for(sight, customer.id in assigned)
        if level is None:
            continue
        summary = CustomerSummary(**_summary(db, keyring, customer, level, team, record.user_id))
        details = keyring.details(customer)
        haystack = (details["name"] + " " + (details["cvr"] or "")).casefold().replace(" ", "")
        if needle in haystack:
            found.append(summary)
    return sorted(found, key=lambda c: c.name.casefold())


@router.post("")
def create_customer(body: CustomerIn, request: Request, admin: Manager, db: DB) -> CustomerDetail:
    customer = Customer(
        wrapped_key=b"", sealed=b"", retention_months=body.retention_months,
        status=body.status, status_date=body.status_date,
        created_at=clock.utcnow(),
        created_by=admin.user_id,
    )
    db.add(customer)
    db.flush()  # the key is bound to the customer's ID
    keyring = Keyring()
    customer.sealed = keyring.give_new_key(customer).seal("customer", customer.id, {
        "name": body.name.strip(), "cvr": body.cvr, "address": body.address.strip(),
    })
    _log(db, request, admin, "customer.created", customer.id)
    db.commit()
    return _detail(db, admin, keyring, customer, "full")


@router.get("/{customer_id}")
def get_customer(customer_id: int, request: Request, record: FullSession, db: DB
                 ) -> CustomerDetail:
    customer, level = visible_customer(db, request, record, customer_id, need="metadata")
    return _detail(db, record, Keyring(), customer, level)


@router.patch("/{customer_id}")
def update_customer(customer_id: int, body: CustomerUpdate, request: Request, admin: Editor,
                    db: DB) -> CustomerDetail:
    customer, _ = visible_customer(db, request, admin, customer_id)
    new_status = body.status is not None and (
        (body.status, body.status_date) != (customer.status, customer.status_date))
    if body.retention_months not in (None, customer.retention_months) or new_status:
        require(Capability.MANAGE_CUSTOMERS)(request, admin, db)
    keyring = Keyring()
    details = dict(keyring.details(customer))
    changed: list[str] = []
    wanted = {
        "name": body.name.strip() if body.name is not None else details["name"],
        "cvr": body.cvr if "cvr" in body.model_fields_set else details["cvr"],
        "address": body.address.strip() if body.address is not None else details["address"],
    }
    if wanted != details:
        changed += sorted(name for name in wanted if wanted[name] != details[name])
        customer.sealed = keyring.sealer(customer).seal("customer", customer.id, wanted)
    retention = body.retention_months
    if retention is not None and retention != customer.retention_months:
        customer.retention_months = retention
        changed.append("retention_months")
    if new_status:
        _log(db, request, admin, "customer.status_changed", customer.id, {
            "from": customer.status, "to": body.status,
            "date": body.status_date.isoformat() if body.status_date else None,
        })
        customer.status, customer.status_date = body.status or "active", body.status_date
    if changed:
        _log(db, request, admin, "customer.updated", customer.id, {"fields": changed})
    db.commit()
    return _detail(db, admin, keyring, customer, "full")


@router.delete("/{customer_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_customer(customer_id: int, body: Annotated[DeleteRequest, Body()], request: Request,
                    admin: Deleter, db: DB) -> None:
    """Delete a customer and everything under it. Its key goes with it, so whatever
    was sealed with it is unreadable from then on (crypto-shredding)."""
    customer, _ = visible_customer(db, request, admin, customer_id)
    if body.confirm_name.strip() != Keyring().name(customer):
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Type the customer's name exactly to confirm.")
    require_step_up(admin)
    remove_image(db, logo_key(customer.id))
    db.delete(customer)
    _log(db, request, admin, "customer.deleted", customer_id)
    db.commit()


# Sites and contacts. Both are sealed; the audit log names them by ID only.


def _site(db: Session, customer: Customer, site_id: int) -> CustomerSite:
    site = db.get(CustomerSite, site_id)
    if site is None or site.customer_id != customer.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That site doesn't exist.")
    return site


def _site_fields(db: Session, customer: Customer, body: SiteIn) -> dict[str, Any]:
    if body.contact_id is not None:
        _contact(db, customer, body.contact_id, status.HTTP_422_UNPROCESSABLE_CONTENT)
    fields: dict[str, Any] = {
        name: getattr(body, name).strip()
        for name in ("name", "address", "opening_hours", "access", "parking", "note")
    }
    return fields | {"kind": body.kind, "contact_id": body.contact_id}


@router.post("/{customer_id}/sites")
def add_site(customer_id: int, body: SiteIn, request: Request, admin: Editor, db: DB
             ) -> CustomerDetail:
    customer, _ = visible_customer(db, request, admin, customer_id)
    keyring = Keyring()
    site = CustomerSite(customer_id=customer.id, sealed=b"")
    db.add(site)
    db.flush()
    site.sealed = keyring.sealer(customer).seal("site", site.id, _site_fields(db, customer, body))
    _log(db, request, admin, "customer.site_added", customer.id, {"site": site.id})
    db.commit()
    return _detail(db, admin, keyring, customer, "full")


@router.put("/{customer_id}/sites/{site_id}")
def update_site(customer_id: int, site_id: int, body: SiteIn, request: Request, admin: Editor,
                db: DB) -> CustomerDetail:
    customer, _ = visible_customer(db, request, admin, customer_id)
    keyring = Keyring()
    site = _site(db, customer, site_id)
    site.sealed = keyring.sealer(customer).seal("site", site.id, _site_fields(db, customer, body))
    _log(db, request, admin, "customer.site_changed", customer.id, {"site": site.id})
    db.commit()
    return _detail(db, admin, keyring, customer, "full")


@router.delete("/{customer_id}/sites/{site_id}")
def remove_site(customer_id: int, site_id: int, request: Request, admin: Editor, db: DB
                ) -> CustomerDetail:
    customer, _ = visible_customer(db, request, admin, customer_id)
    keyring = Keyring()
    db.delete(_site(db, customer, site_id))
    contacts = db.scalars(select(CustomerContact).where(CustomerContact.customer_id == customer.id))
    _unlink(contacts, keyring.sealer(customer), "contact", "site_id", site_id)
    systems = db.scalars(select(CustomerSystem).where(CustomerSystem.customer_id == customer.id))
    _unlink(systems, keyring.sealer(customer), "system", "site_id", site_id)
    _log(db, request, admin, "customer.site_removed", customer.id, {"site": site_id})
    db.commit()
    return _detail(db, admin, Keyring(), customer, "full")


def _contact(db: Session, customer: Customer, contact_id: int,
             missing: int = status.HTTP_404_NOT_FOUND) -> CustomerContact:
    contact = db.get(CustomerContact, contact_id)
    if contact is None or contact.customer_id != customer.id:
        raise HTTPException(missing, "That contact doesn't exist.")
    return contact


def _contact_fields(db: Session, customer: Customer, body: ContactIn) -> dict[str, Any]:
    if body.site_id is not None:
        site = db.get(CustomerSite, body.site_id)
        if site is None or site.customer_id != customer.id:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "That site doesn't exist.")
    fields: dict[str, Any] = {
        name: getattr(body, name).strip()
        for name in ("name", "role", "email", "phone", "may_contact_note")
    }
    return fields | {"roles": body.roles, "site_id": body.site_id, "may_contact": body.may_contact,
                     "preferred_channel": body.preferred_channel}


def _unlink(records: Iterable[CustomerSite | CustomerContact | CustomerSystem], sealer: Sealer,
            kind: str, field: str, removed_id: int) -> None:
    """Take a removed site or contact out of the records that point at it (the
    references are sealed, so the database can't do it)."""
    for record in records:
        value = sealer.open(kind, record.id, record.sealed)
        if value.get(field) == removed_id:
            record.sealed = sealer.seal(kind, record.id, value | {field: None})


@router.post("/{customer_id}/contacts")
def add_contact(customer_id: int, body: ContactIn, request: Request, admin: Editor, db: DB
                ) -> CustomerDetail:
    customer, _ = visible_customer(db, request, admin, customer_id)
    keyring = Keyring()
    contact = CustomerContact(customer_id=customer.id, sealed=b"")
    db.add(contact)
    db.flush()
    contact.sealed = keyring.sealer(customer).seal(
        "contact", contact.id, _contact_fields(db, customer, body))
    _log(db, request, admin, "customer.contact_added", customer.id, {"contact": contact.id})
    db.commit()
    return _detail(db, admin, keyring, customer, "full")


@router.put("/{customer_id}/contacts/{contact_id}")
def update_contact(customer_id: int, contact_id: int, body: ContactIn, request: Request,
                   admin: Editor, db: DB) -> CustomerDetail:
    customer, _ = visible_customer(db, request, admin, customer_id)
    keyring = Keyring()
    contact = _contact(db, customer, contact_id)
    contact.sealed = keyring.sealer(customer).seal(
        "contact", contact.id, _contact_fields(db, customer, body))
    _log(db, request, admin, "customer.contact_changed", customer.id, {"contact": contact.id})
    db.commit()
    return _detail(db, admin, keyring, customer, "full")


@router.delete("/{customer_id}/contacts/{contact_id}")
def remove_contact(customer_id: int, contact_id: int, request: Request, admin: Editor, db: DB
                   ) -> CustomerDetail:
    customer, _ = visible_customer(db, request, admin, customer_id)
    keyring = Keyring()
    db.delete(_contact(db, customer, contact_id))
    sites = db.scalars(select(CustomerSite).where(CustomerSite.customer_id == customer.id))
    _unlink(sites, keyring.sealer(customer), "site", "contact_id", contact_id)
    _log(db, request, admin, "customer.contact_removed", customer.id, {"contact": contact_id})
    db.commit()
    return _detail(db, admin, Keyring(), customer, "full")


# The group's other companies


def _company(db: Session, customer: Customer, company_id: int) -> CustomerCompany:
    company = db.get(CustomerCompany, company_id)
    if company is None or company.customer_id != customer.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That company doesn't exist.")
    return company


def _company_fields(body: CompanyIn) -> dict[str, Any]:
    return {"name": body.name.strip(), "cvr": body.cvr, "address": body.address.strip()}


@router.post("/{customer_id}/companies")
def add_company(customer_id: int, body: CompanyIn, request: Request, admin: Editor, db: DB
                ) -> CustomerDetail:
    customer, _ = visible_customer(db, request, admin, customer_id)
    keyring = Keyring()
    company = CustomerCompany(customer_id=customer.id, sealed=b"")
    db.add(company)
    db.flush()
    company.sealed = keyring.sealer(customer).seal("company", company.id, _company_fields(body))
    _log(db, request, admin, "customer.company_added", customer.id, {"company": company.id})
    db.commit()
    return _detail(db, admin, keyring, customer, "full")


@router.put("/{customer_id}/companies/{company_id}")
def change_company(customer_id: int, company_id: int, body: CompanyIn, request: Request,
                   admin: Editor, db: DB) -> CustomerDetail:
    customer, _ = visible_customer(db, request, admin, customer_id)
    keyring = Keyring()
    company = _company(db, customer, company_id)
    company.sealed = keyring.sealer(customer).seal("company", company.id, _company_fields(body))
    _log(db, request, admin, "customer.company_changed", customer.id, {"company": company.id})
    db.commit()
    return _detail(db, admin, keyring, customer, "full")


@router.delete("/{customer_id}/companies/{company_id}")
def remove_company(customer_id: int, company_id: int, request: Request, admin: Editor, db: DB
                   ) -> CustomerDetail:
    customer, _ = visible_customer(db, request, admin, customer_id)
    _drop_from_services(db, Keyring().sealer(customer), "company_id", company_id)
    _drop_from_agreements(db, Keyring().sealer(customer), company_id=company_id)
    db.delete(_company(db, customer, company_id))
    _log(db, request, admin, "customer.company_removed", customer.id, {"company": company_id})
    db.commit()
    return _detail(db, admin, Keyring(), customer, "full")


# Systems


def _system(db: Session, customer: Customer, system_id: int,
            missing: int = status.HTTP_404_NOT_FOUND) -> CustomerSystem:
    system = db.get(CustomerSystem, system_id)
    if system is None or system.customer_id != customer.id:
        raise HTTPException(missing, "That system doesn't exist.")
    return system


def _check_system(db: Session, customer: Customer, body: SystemIn, system_id: int | None
                  ) -> None:
    """Its host and site are the same customer's, and it never runs on itself."""
    if body.site_id is not None:
        site = db.get(CustomerSite, body.site_id)
        if site is None or site.customer_id != customer.id:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "That site doesn't exist.")
    if body.parent_id is not None:
        _system(db, customer, body.parent_id, status.HTTP_422_UNPROCESSABLE_CONTENT)
        if would_loop(db, system_id, body.parent_id):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                                "A system can't run on itself, or on what runs on it.")


@router.post("/{customer_id}/systems")
def add_system(customer_id: int, body: SystemIn, request: Request, admin: Editor, db: DB
               ) -> CustomerDetail:
    customer, _ = visible_customer(db, request, admin, customer_id)
    _check_system(db, customer, body, None)
    keyring = Keyring()
    system = CustomerSystem(customer_id=customer.id, parent_id=body.parent_id, sealed=b"",
                            warranty_end=body.warranty_end, retired_on=body.retired_on)
    db.add(system)
    db.flush()
    system.sealed = keyring.sealer(customer).seal("system", system.id, sealed_fields(body))
    _log(db, request, admin, "customer.system_added", customer.id, {"system": system.id})
    db.commit()
    return _detail(db, admin, keyring, customer, "full")


@router.put("/{customer_id}/systems/{system_id}")
def change_system(customer_id: int, system_id: int, body: SystemIn, request: Request,
                  admin: Editor, db: DB) -> CustomerDetail:
    customer, _ = visible_customer(db, request, admin, customer_id)
    system = _system(db, customer, system_id)
    _check_system(db, customer, body, system.id)
    keyring = Keyring()
    system.parent_id, system.warranty_end, system.retired_on = (
        body.parent_id, body.warranty_end, body.retired_on)
    system.sealed = keyring.sealer(customer).seal("system", system.id, sealed_fields(body))
    _log(db, request, admin, "customer.system_changed", customer.id, {"system": system.id})
    db.commit()
    return _detail(db, admin, keyring, customer, "full")


@router.delete("/{customer_id}/systems/{system_id}")
def remove_system(customer_id: int, system_id: int, request: Request, admin: Editor, db: DB
                  ) -> CustomerDetail:
    """Remove a system; what ran on it stays, without a host."""
    customer, _ = visible_customer(db, request, admin, customer_id)
    system = _system(db, customer, system_id)
    for guest in db.scalars(select(CustomerSystem).where(CustomerSystem.parent_id == system.id)):
        guest.parent_id = None
    _drop_from_services(db, Keyring().sealer(customer), "systems", system.id)
    db.delete(system)
    _log(db, request, admin, "customer.system_removed", customer.id, {"system": system_id})
    db.commit()
    return _detail(db, admin, Keyring(), customer, "full")


# The customer's services


def _service(db: Session, customer: Customer, service_id: int) -> CustomerService:
    service = db.get(CustomerService, service_id)
    if service is None or service.customer_id != customer.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That service doesn't exist.")
    return service


def _drop_from_services(db: Session, sealer: Sealer, field: str, removed_id: int) -> None:
    """Take a removed system or company out of the customer's services."""
    rows = db.scalars(select(CustomerService)
                      .where(CustomerService.customer_id == sealer.customer_id))
    for row in rows:
        value = sealer.open("service", row.id, row.sealed)
        if field == "systems":
            kept = [s for s in value.get("systems", []) if s.get("system_id") != removed_id]
            changed = len(kept) != len(value.get("systems", []))
            value["systems"] = kept
        else:
            changed = value.get(field) == removed_id
            value[field] = None if changed else value.get(field)
        if changed:
            row.sealed = sealer.seal("service", row.id, value)


@router.post("/{customer_id}/services")
def add_service(customer_id: int, body: CustomerServiceIn, request: Request, admin: Manager,
                db: DB) -> CustomerDetail:
    customer, _ = visible_customer(db, request, admin, customer_id)
    standard = db.get(StandardService, body.standard_service_id or -1)
    if standard is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                            "Choose a standard service to start from.")
    fields = service_fields(db, customer, body, standard, {})
    keyring = Keyring()
    service = CustomerService(customer_id=customer.id, standard_service_id=standard.id,
                              status=body.status, started_on=body.started_on,
                              ended_on=body.ended_on, sealed=b"")
    db.add(service)
    db.flush()
    service.sealed = keyring.sealer(customer).seal("service", service.id, fields)
    _log(db, request, admin, "customer.service_added", customer.id,
         {"service": service.id, "standard": standard.id})
    db.commit()
    return _detail(db, admin, keyring, customer, "full")


@router.put("/{customer_id}/services/{service_id}")
def change_service(customer_id: int, service_id: int, body: CustomerServiceIn, request: Request,
                   admin: Manager, db: DB) -> CustomerDetail:
    customer, _ = visible_customer(db, request, admin, customer_id)
    service = _service(db, customer, service_id)
    keyring = Keyring()
    sealer = keyring.sealer(customer)
    before = sealer.open("service", service.id, service.sealed)
    standard = db.get(StandardService, service.standard_service_id or -1)
    fields = service_fields(db, customer, body, standard, before)
    changes: dict[str, object] = {"service": service.id}
    if service.status != body.status:
        changes["status"] = [service.status, body.status]
    if before.get("case_number") != fields["case_number"]:
        changes["case_number_changed"] = True
    service.status, service.started_on, service.ended_on = (
        body.status, body.started_on, body.ended_on)
    service.sealed = sealer.seal("service", service.id, fields)
    _log(db, request, admin, "customer.service_changed", customer.id, changes)
    db.commit()
    return _detail(db, admin, keyring, customer, "full")


@router.delete("/{customer_id}/services/{service_id}")
def remove_service(customer_id: int, service_id: int, request: Request, admin: Manager, db: DB
                   ) -> CustomerDetail:
    """Remove a service entered by mistake. One the customer had keeps its history:
    end it instead."""
    customer, _ = visible_customer(db, request, admin, customer_id)
    db.delete(_service(db, customer, service_id))
    _drop_from_agreements(db, Keyring().sealer(customer), service_id=service_id)
    _log(db, request, admin, "customer.service_removed", customer.id, {"service": service_id})
    db.commit()
    return _detail(db, admin, Keyring(), customer, "full")


# Agreements


def _agreement(db: Session, customer: Customer, agreement_id: int) -> CustomerAgreement:
    agreement = db.get(CustomerAgreement, agreement_id)
    if agreement is None or agreement.customer_id != customer.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That agreement doesn't exist.")
    return agreement


def _drop_from_agreements(db: Session, sealer: Sealer, *, service_id: int | None = None,
                          company_id: int | None = None) -> None:
    """Take a removed service or company out of the customer's agreements: the
    section stays, no longer linked."""
    rows = db.scalars(select(CustomerAgreement)
                      .where(CustomerAgreement.customer_id == sealer.customer_id))
    for row in rows:
        value = sealer.open("agreement", row.id, row.sealed)
        changed = False
        for section in value.get("sections", []):
            if service_id is not None and section.get("service_id") == service_id:
                section["service_id"], changed = None, True
        if company_id is not None and value.get("company_id") == company_id:
            value["company_id"], changed = None, True
        if changed:
            row.sealed = sealer.seal("agreement", row.id, value)


def _set_agreement(agreement: CustomerAgreement, body: AgreementIn) -> None:
    agreement.status, agreement.starts_on, agreement.ends_on = (
        body.status, body.starts_on, body.ends_on)
    agreement.notice_by, agreement.auto_renews = body.notice_by, body.auto_renews


@router.post("/{customer_id}/agreements")
def add_agreement(customer_id: int, body: AgreementIn, request: Request, admin: Agreer, db: DB
                  ) -> CustomerDetail:
    customer, _ = visible_customer(db, request, admin, customer_id)
    fields = agreement_fields(db, customer, body)
    keyring = Keyring()
    agreement = CustomerAgreement(customer_id=customer.id, sealed=b"")
    _set_agreement(agreement, body)
    db.add(agreement)
    db.flush()
    agreement.sealed = keyring.sealer(customer).seal("agreement", agreement.id, fields)
    _log(db, request, admin, "customer.agreement_added", customer.id,
         {"agreement": agreement.id, "status": body.status})
    db.commit()
    return _detail(db, admin, keyring, customer, "full")


@router.put("/{customer_id}/agreements/{agreement_id}")
def change_agreement(customer_id: int, agreement_id: int, body: AgreementIn, request: Request,
                     admin: Agreer, db: DB) -> CustomerDetail:
    customer, _ = visible_customer(db, request, admin, customer_id)
    agreement = _agreement(db, customer, agreement_id)
    fields = agreement_fields(db, customer, body)
    keyring = Keyring()
    changes: dict[str, object] = {"agreement": agreement.id}
    if agreement.status != body.status:
        changes["status"] = [agreement.status, body.status]
    _set_agreement(agreement, body)
    agreement.sealed = keyring.sealer(customer).seal("agreement", agreement.id, fields)
    _log(db, request, admin, "customer.agreement_changed", customer.id, changes)
    db.commit()
    return _detail(db, admin, keyring, customer, "full")


@router.delete("/{customer_id}/agreements/{agreement_id}")
def remove_agreement(customer_id: int, agreement_id: int, request: Request, admin: Agreer,
                     db: DB) -> CustomerDetail:
    """Remove an agreement entered by mistake. One that ran keeps its history: end
    it instead."""
    customer, _ = visible_customer(db, request, admin, customer_id)
    db.delete(_agreement(db, customer, agreement_id))
    _log(db, request, admin, "customer.agreement_removed", customer.id,
         {"agreement": agreement_id})
    db.commit()
    return _detail(db, admin, Keyring(), customer, "full")


# Pinned warnings


def _pin(db: Session, customer: Customer, pin_id: int) -> CustomerPin:
    pin = db.get(CustomerPin, pin_id)
    if pin is None or pin.customer_id != customer.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That pinned warning doesn't exist.")
    return pin


@router.post("/{customer_id}/pins")
def add_pin(customer_id: int, body: PinIn, request: Request, admin: Manager, db: DB
            ) -> CustomerDetail:
    customer, _ = visible_customer(db, request, admin, customer_id)
    pinned = db.scalar(select(func.count()).select_from(CustomerPin)
                       .where(CustomerPin.customer_id == customer.id)) or 0
    if pinned >= PINS_PER_CUSTOMER:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"A customer has at most {PINS_PER_CUSTOMER} pinned warnings: unpin one first.",
        )
    keyring = Keyring()
    pin = CustomerPin(customer_id=customer.id, sealed=b"", pinned_by=admin.user_id,
                      pinned_at=clock.utcnow())
    db.add(pin)
    db.flush()
    pin.sealed = keyring.sealer(customer).seal("pin", pin.id, {
        "text": body.text.strip(), "severity": body.severity})
    _log(db, request, admin, "customer.pin_added", customer.id, {"pin": pin.id})
    db.commit()
    return _detail(db, admin, keyring, customer, "full")


@router.put("/{customer_id}/pins/{pin_id}")
def change_pin(customer_id: int, pin_id: int, body: PinIn, request: Request, admin: Manager,
               db: DB) -> CustomerDetail:
    customer, _ = visible_customer(db, request, admin, customer_id)
    keyring = Keyring()
    pin = _pin(db, customer, pin_id)
    pin.sealed = keyring.sealer(customer).seal("pin", pin.id, {
        "text": body.text.strip(), "severity": body.severity})
    _log(db, request, admin, "customer.pin_changed", customer.id, {"pin": pin.id})
    db.commit()
    return _detail(db, admin, keyring, customer, "full")


@router.delete("/{customer_id}/pins/{pin_id}")
def remove_pin(customer_id: int, pin_id: int, request: Request, admin: Manager, db: DB
               ) -> CustomerDetail:
    customer, _ = visible_customer(db, request, admin, customer_id)
    db.delete(_pin(db, customer, pin_id))
    _log(db, request, admin, "customer.pin_removed", customer.id, {"pin": pin_id})
    db.commit()
    return _detail(db, admin, Keyring(), customer, "full")


# Who's assigned


@router.put("/{customer_id}/assignments")
def set_assignments(customer_id: int, body: Assignments, request: Request, admin: Manager,
                    db: DB) -> CustomerDetail:
    customer, _ = visible_customer(db, request, admin, customer_id)
    wanted = set(body.people)
    if not wanted <= set(_assignable_ids(db)):
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Only active technicians can be assigned to a customer.")
    current = {a.user_id: a for a in db.scalars(
        select(CustomerAssignment).where(CustomerAssignment.customer_id == customer.id))}
    changed = wanted ^ set(current)
    usernames = {u.id: u.username for u in db.scalars(select(User).where(User.id.in_(changed)))}
    for user_id in sorted(changed):
        if user_id in current:
            db.delete(current[user_id])
            _log(db, request, admin, "customer.unassigned", customer.id,
                 {"user": usernames.get(user_id)})
        else:
            db.add(CustomerAssignment(customer_id=customer.id, user_id=user_id,
                                      assigned_at=clock.utcnow(), assigned_by=admin.user_id))
            _log(db, request, admin, "customer.assigned", customer.id,
                 {"user": usernames.get(user_id)})
    db.commit()
    return _detail(db, admin, Keyring(), customer, "full")


# Logo


@router.put("/{customer_id}/logo")
def upload_logo(
    customer_id: int, data: Annotated[bytes, Body(media_type="application/octet-stream")],
    request: Request, admin: Manager, db: DB,
) -> CustomerDetail:
    customer, _ = visible_customer(db, request, admin, customer_id)
    try:
        png = clean_image(data, max_size=LOGO_SIZE)
    except ImageRejected as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    store_image(db, logo_key(customer.id), png)
    _log(db, request, admin, "customer.logo_changed", customer.id)
    db.commit()
    return _detail(db, admin, Keyring(), customer, "full")


@router.delete("/{customer_id}/logo")
def remove_logo(customer_id: int, request: Request, admin: Manager, db: DB) -> CustomerDetail:
    customer, _ = visible_customer(db, request, admin, customer_id)
    if remove_image(db, logo_key(customer.id)):
        _log(db, request, admin, "customer.logo_removed", customer.id)
    db.commit()
    return _detail(db, admin, Keyring(), customer, "full")


@router.get("/{customer_id}/logo")
def get_logo(customer_id: int, request: Request, record: FullSession, db: DB) -> Response:
    visible_customer(db, request, record, customer_id)
    image = load_image(db, logo_key(customer_id))
    if image is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No logo is set.")
    return Response(image.data, media_type=image.content_type, headers=IMAGE_HEADERS)
