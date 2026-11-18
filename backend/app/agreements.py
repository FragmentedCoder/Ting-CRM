"""A customer's agreements: what was signed, what it covers, and when it runs out.

An agreement is the signed document (or an accepted quote, or a confirmation by
email) behind one or more of the customer's services. Þing records its versions
(when each was sent and signed, and by whom), its term (start, end, the last day
to give notice, whether it renews by itself), and its sections: each section of
the document with the agreed text and the customer service it covers, or marked
as terms. A service some active agreement's section covers is Covered; work on
any other is Billable, and the service is flagged "No agreement".

Þing keeps no prices: an agreement points to the section of its document on
price and invoicing. The document itself is uploaded with Documents (Phase 3).

All of it is sealed with the customer's key, except what lists and warnings
need: its status and its dates. Managers and Administrators create and change
agreements (MANAGE_AGREEMENTS); everyone who sees the customer reads them. The
routes are in app/customer_routes.py.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Literal, Self

from fastapi import HTTPException, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import Boolean, Date, ForeignKey, LargeBinary, String, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.customer_services import CoveredBy, CustomerService
from app.customers import Customer, CustomerCompany, Sealer
from app.db import Base

AgreementKind = Literal["service", "dpa", "quote", "email", "other"]
AgreementStatus = Literal["offer", "active", "ended"]


class CustomerAgreement(Base):
    __tablename__ = "customer_agreements"
    __table_args__ = {"sqlite_autoincrement": True}

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), index=True
    )
    # An offer waiting for the customer, active, or ended.
    status: Mapped[str] = mapped_column(String(10), default="active")
    starts_on: Mapped[date | None] = mapped_column(Date)
    # The end of the current term, or the day it ended.
    ends_on: Mapped[date | None] = mapped_column(Date)
    # The last day to give notice before it renews.
    notice_by: Mapped[date | None] = mapped_column(Date)
    auto_renews: Mapped[bool] = mapped_column(Boolean, default=False)
    # {"name", "kind", "company_id", "notice_period", "sla", "price_section",
    #  "versions", "sections", "notes"}
    sealed: Mapped[bytes] = mapped_column(LargeBinary)


class Version(BaseModel):
    number: int = Field(ge=1, le=999)
    sent_on: date | None = None
    signed_on: date | None = None
    signed_for_customer: str = Field(default="", max_length=200)
    signed_for_us: str = Field(default="", max_length=200)
    # Such as where the signed copy is kept, until documents are uploaded to Þing.
    note: str = Field(default="", max_length=300)


class Section(BaseModel):
    # The section's number in the document: "§ 3.1".
    ref: str = Field(min_length=1, max_length=20)
    # What the document says there.
    text: str = Field(default="", max_length=1000)
    # The customer service it covers; none for terms, or a section not linked yet.
    service_id: int | None = None
    terms: bool = False

    @model_validator(mode="after")
    def _one_or_the_other(self) -> Self:
        if self.terms and self.service_id is not None:
            raise ValueError(f"{self.ref} is terms, or covers a service, not both.")
        return self


class AgreementIn(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    kind: AgreementKind = "service"
    status: AgreementStatus = "active"
    starts_on: date | None = None
    ends_on: date | None = None
    notice_by: date | None = None
    auto_renews: bool = False
    # The group company it's with; none for the whole customer.
    company_id: int | None = None
    # In words, as the document has it: "3 months".
    notice_period: str = Field(default="", max_length=100)
    # Its own response times; empty for the company's standard SLA.
    sla: str = Field(default="", max_length=500)
    # Where the document deals with price and invoicing: "§ 5".
    price_section: str = Field(default="", max_length=100)
    versions: list[Version] = Field(default=[], max_length=30)
    sections: list[Section] = Field(default=[], max_length=80)
    notes: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.status == "ended" and self.ends_on is None:
            raise ValueError("Give the day the agreement ended.")
        if self.starts_on and self.ends_on and self.ends_on < self.starts_on:
            raise ValueError("The agreement ends before it starts.")
        numbers = [v.number for v in self.versions]
        if len(numbers) != len(set(numbers)):
            raise ValueError("Two versions have the same number.")
        self.versions.sort(key=lambda v: v.number)
        return self


class AgreementOut(AgreementIn):
    id: int


def sealed_fields(db: Session, customer: Customer, body: AgreementIn) -> dict[str, Any]:
    """What's sealed for an agreement, its company and services checked as this
    customer's."""
    if body.company_id is not None:
        company = db.get(CustomerCompany, body.company_id)
        if company is None or company.customer_id != customer.id:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                                "That company doesn't exist.")
    for section in body.sections:
        if section.service_id is None:
            continue
        service = db.get(CustomerService, section.service_id)
        if service is None or service.customer_id != customer.id:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                                f"{section.ref} covers a service this customer doesn't have.")
    plain = {"status", "starts_on", "ends_on", "notice_by", "auto_renews"}
    fields = body.model_dump(mode="json", exclude=plain)
    return {name: value.strip() if isinstance(value, str) else value
            for name, value in fields.items()}


def agreements_of(db: Session, sealer: Sealer, customer_id: int) -> list[AgreementOut]:
    rows = db.scalars(select(CustomerAgreement)
                      .where(CustomerAgreement.customer_id == customer_id))
    found = [
        AgreementOut(id=row.id, status=_status(row.status), starts_on=row.starts_on,
                     ends_on=row.ends_on, notice_by=row.notice_by, auto_renews=row.auto_renews,
                     **sealer.open("agreement", row.id, row.sealed))
        for row in rows
    ]
    order = {"active": 0, "offer": 1, "ended": 2}
    return sorted(found, key=lambda a: (order[a.status], a.name.casefold()))


def _status(value: str) -> AgreementStatus:
    return "offer" if value == "offer" else "ended" if value == "ended" else "active"


def coverage(agreements: list[AgreementOut]) -> dict[int, CoveredBy]:
    """Which active agreement's section covers each customer service."""
    covered: dict[int, CoveredBy] = {}
    for agreement in agreements:
        if agreement.status != "active":
            continue
        for section in agreement.sections:
            if section.service_id is not None and section.service_id not in covered:
                covered[section.service_id] = CoveredBy(
                    agreement_id=agreement.id, name=agreement.name, section=section.ref)
    return covered
