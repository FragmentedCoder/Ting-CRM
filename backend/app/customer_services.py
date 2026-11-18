"""A customer's services: each a copy of a standard service, made the customer's own.

A customer who has Backup gets a customer service copied from the standard Backup:
its details filled in for this customer, details added just for them, standard
details marked as not used here, the systems it covers with a note on each, and
the case number its work goes on ("Log time on"). Changing the standard never
rewrites the copy: a detail the standard gains shows up here empty, and one it
drops stays with what was filled in, under the label it had.

Case numbers belong to the company's time registration system; Þing records
them, with their kind (monthly, standing or project), and keeps a monthly one's
earlier numbers when it's replaced.

All of it is sealed with the customer's key, except what lists and warnings need:
which standard it came from, whether it's active, and its dates. Managers and
Administrators add and change a customer's services (MANAGE_CUSTOMERS);
everyone who sees the customer reads them. The routes are in
app/customer_routes.py.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Literal, Self

from fastapi import HTTPException, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import Date, ForeignKey, Integer, LargeBinary, String, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.customers import Customer, CustomerCompany, CustomerSystem, Sealer
from app.db import Base
from app.services import DetailField, StandardService, details_of

CaseKind = Literal["", "monthly", "standing", "project"]
Value = str | float | bool | None


class CustomerService(Base):
    __tablename__ = "customer_services"
    __table_args__ = {"sqlite_autoincrement": True}

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), index=True
    )
    standard_service_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("standard_services.id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(String(10), default="active")
    started_on: Mapped[date | None] = mapped_column(Date)
    ended_on: Mapped[date | None] = mapped_column(Date)
    # {"name", "company_id", "values", "fields", "extra", "not_used", "systems",
    #  "case_number", "case_kind", "case_history", "notes"}
    sealed: Mapped[bytes] = mapped_column(LargeBinary)


class ExtraDetail(DetailField):
    """A detail added for this customer only."""

    value: Value = None


class CoveredSystem(BaseModel):
    system_id: int
    # What's special about this system for this service: "Stop the booking service
    # before a restore".
    note: str = Field(default="", max_length=300)


class PastCase(BaseModel):
    number: str
    kind: CaseKind
    until: date


class CustomerServiceIn(BaseModel):
    standard_service_id: int | None = None
    status: Literal["active", "ended"] = "active"
    started_on: date | None = None
    ended_on: date | None = None
    # The group company it's for; none for the whole customer.
    company_id: int | None = None
    # The standard's details, filled in: key -> value.
    values: dict[str, Value] = Field(default={}, max_length=60)
    extra: list[ExtraDetail] = Field(default=[], max_length=30)
    # Standard details this customer doesn't need.
    not_used: list[str] = Field(default=[], max_length=60)
    systems: list[CoveredSystem] = Field(default=[], max_length=100)
    case_number: str = Field(default="", max_length=30, pattern=r"^[A-Za-z0-9\-/]*$")
    case_kind: CaseKind = ""
    notes: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.status == "ended" and self.ended_on is None:
            raise ValueError("Give the day the service ended.")
        if self.status == "active":
            self.ended_on = None
        for value in self.values.values():
            if isinstance(value, str) and len(value) > 1000:
                raise ValueError("A detail holds at most 1000 characters.")
        return self


class Detail(DetailField):
    value: Value = None
    # Added for this customer, not from the standard.
    added: bool = False
    # From the standard once, since dropped from it; kept with what was filled in.
    kept: bool = False


class CustomerServiceOut(BaseModel):
    id: int
    standard_service_id: int | None
    # The standard it came from, or (once that's gone) the name it had.
    name: str
    status: Literal["active", "ended"]
    started_on: date | None
    ended_on: date | None
    company_id: int | None
    details: list[Detail]
    not_used: list[DetailField]
    systems: list[CoveredSystem]
    case_number: str
    case_kind: CaseKind
    case_history: list[PastCase]
    notes: str


def _value(field: DetailField, value: Value) -> Value:
    """A value as its detail's kind takes it; refused when it isn't one."""
    if value is None or value == "":
        return None
    ok = {
        "text": isinstance(value, str),
        "number": isinstance(value, (int, float)) and not isinstance(value, bool),
        "date": isinstance(value, str) and _is_date(value),
        "yes_no": isinstance(value, bool),
        "choice": isinstance(value, str) and value in field.choices,
    }[field.kind]
    if not ok:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                            f"“{value}” doesn't fit {field.label}.")
    return value.strip() if isinstance(value, str) else value


def _is_date(value: str) -> bool:
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def sealed_fields(db: Session, customer: Customer, body: CustomerServiceIn,
                  standard: StandardService | None, before: dict[str, Any]) -> dict[str, Any]:
    """What's sealed for a customer service, checked against the customer and the
    standard. `before` is what was sealed until now ({} for a new one)."""
    if body.company_id is not None:
        company = db.get(CustomerCompany, body.company_id)
        if company is None or company.customer_id != customer.id:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                                "That company doesn't exist.")
    systems = {s.system_id: s for s in body.systems}
    for system_id in systems:
        system = db.get(CustomerSystem, system_id)
        if system is None or system.customer_id != customer.id:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                                "That system doesn't exist.")
    standard_fields = {f.key: f for f in details_of(standard)} if standard else {}
    known = standard_fields | {f.key: DetailField(**f.model_dump(exclude={"value"}))
                               for f in body.extra}
    kept = {f["key"]: DetailField.model_validate(f) for f in before.get("fields", [])}
    values: dict[str, Value] = {}
    for key, value in body.values.items():
        field = known.get(key) or kept.get(key)
        if field is None:
            owner = standard.name if standard else "This service"
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                                f"{owner} has no detail “{key}”.")
        if (checked := _value(field, value)) is not None:
            values[key] = checked
    extra_keys = {f.key for f in body.extra}
    if extra_keys & standard_fields.keys():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                            "An added detail has the name of one the standard has.")
    history = [PastCase.model_validate(c).model_dump(mode="json")
               for c in before.get("case_history", [])]
    if before.get("case_number") and before["case_number"] != body.case_number:
        history.insert(0, PastCase(number=before["case_number"], kind=before.get("case_kind", ""),
                                   until=date.today()).model_dump(mode="json"))
    return {
        "name": standard.name if standard else str(before.get("name", "")),
        "company_id": body.company_id,
        "values": values,
        # The definitions of every standard detail with a value, so a detail the
        # standard drops later keeps its label here.
        "fields": [standard_fields[k].model_dump() for k in values if k in standard_fields]
                  + [f.model_dump() for k, f in kept.items()
                     if k in values and k not in standard_fields],
        "extra": [{**f.model_dump(exclude={"value"}), "value": _value(f, f.value)}
                  for f in body.extra],
        "not_used": sorted(k for k in set(body.not_used) if k in standard_fields),
        "systems": [s.model_dump() for s in systems.values()],
        "case_number": body.case_number.strip(),
        "case_kind": body.case_kind,
        "case_history": history[:24],
        "notes": body.notes.strip(),
    }


def services_of(db: Session, sealer: Sealer, customer_id: int) -> list[CustomerServiceOut]:
    rows = db.scalars(select(CustomerService).where(CustomerService.customer_id == customer_id))
    standards = {s.id: s for s in db.scalars(select(StandardService))}
    found = [describe(row, sealer.open("service", row.id, row.sealed),
                      standards.get(row.standard_service_id or -1)) for row in rows]
    # Active first, then by name.
    return sorted(found, key=lambda s: (s.status != "active", s.name.casefold()))


def describe(row: CustomerService, sealed: dict[str, Any],
             standard: StandardService | None) -> CustomerServiceOut:
    values: dict[str, Value] = sealed.get("values", {})
    not_used = set(sealed.get("not_used", []))
    standard_fields = details_of(standard) if standard else []
    details = [Detail(**f.model_dump(), value=values.get(f.key))
               for f in standard_fields if f.key not in not_used]
    current = {f.key for f in standard_fields}
    details += [Detail(**DetailField.model_validate(f).model_dump(), value=values.get(f["key"]),
                       kept=True)
                for f in sealed.get("fields", []) if f["key"] not in current]
    details += [Detail(**ExtraDetail.model_validate(f).model_dump(), added=True)
                for f in sealed.get("extra", [])]
    return CustomerServiceOut(
        id=row.id, standard_service_id=row.standard_service_id,
        name=standard.name if standard else str(sealed.get("name", "")),
        status="ended" if row.status == "ended" else "active",
        started_on=row.started_on, ended_on=row.ended_on,
        company_id=sealed.get("company_id"), details=details,
        not_used=[f for f in standard_fields if f.key in not_used],
        systems=[CoveredSystem.model_validate(s) for s in sealed.get("systems", [])],
        case_number=str(sealed.get("case_number", "")),
        case_kind=sealed.get("case_kind", ""),
        case_history=[PastCase.model_validate(c) for c in sealed.get("case_history", [])],
        notes=str(sealed.get("notes", "")),
    )
