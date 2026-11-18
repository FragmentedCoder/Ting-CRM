"""Standard services: the catalog every customer's services are copied from.

Backup is one entry here, with the details worth recording for any customer who
has it (the product, where the copies go, how long they're kept). Each customer
who has Backup gets a copy of its own, which keeps the details it was given and
can add or drop some (app/customer_services.py). Changing a standard service
never rewrites a customer's copy: details added here show up on the copies,
empty, to fill in.

The catalog is the company's own, not customer data, so it isn't sealed. Managers
and Administrators keep it (MANAGE_SERVICE_CATALOG); everyone who works with
customers reads it. Every change is logged. Migration 0021 starts it with the
team's list, for Managers to change.
"""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime
from typing import Annotated, Literal, Self

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import Integer, String, Text, func, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from app import audit, clock
from app.auth.dependencies import DB, FullSession, client_ip, require
from app.auth.sessions import UserSession
from app.db import Base, UTCDateTime
from app.roles import Capability

DetailKind = Literal["text", "number", "date", "yes_no", "choice"]

router = APIRouter(prefix="/services")
Keeper = Annotated[UserSession, Depends(require(Capability.MANAGE_SERVICE_CATALOG))]


class StandardService(Base):
    __tablename__ = "standard_services"
    __table_args__ = {"sqlite_autoincrement": True}

    id: Mapped[int] = mapped_column(primary_key=True)
    # What Þing itself looks for, such as "support" for the overview's Support
    # tile; None for a service Managers added.
    key: Mapped[str | None] = mapped_column(String(40), unique=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    description: Mapped[str] = mapped_column(String(500), default="")
    # A JSON list of DetailField.
    details: Mapped[str] = mapped_column(Text, default="[]")
    position: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)


class DetailField(BaseModel):
    # Made from the label when left out; the same key keeps a detail's value on the
    # customers' copies when its label is reworded.
    key: str = Field(default="", max_length=60, pattern=r"^[a-z0-9_]*$")
    label: str = Field(min_length=1, max_length=80)
    kind: DetailKind = "text"
    choices: list[str] = Field(default=[], max_length=20)
    help: str = Field(default="", max_length=200)

    @model_validator(mode="after")
    def _choices(self) -> Self:
        self.choices = [c.strip() for c in self.choices if c.strip()]
        if self.kind == "choice" and not self.choices:
            raise ValueError(f"Give the choices for “{self.label}”.")
        if self.kind != "choice":
            self.choices = []
        self.key = self.key or slug(self.label)
        return self


class ServiceIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=500)
    details: list[DetailField] = Field(default=[], max_length=40)

    @model_validator(mode="after")
    def _distinct(self) -> Self:
        keys = [d.key for d in self.details]
        if len(keys) != len(set(keys)):
            raise ValueError("Two details have the same name.")
        return self


class ServiceOut(ServiceIn):
    id: int
    key: str | None
    # How many customers have a copy (any status).
    used_by: int = 0


def slug(label: str) -> str:
    plain = unicodedata.normalize("NFKD", label.casefold()).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "_", plain).strip("_")[:60] or "detail"


def details_of(service: StandardService) -> list[DetailField]:
    return [DetailField.model_validate(d) for d in json.loads(service.details or "[]")]


def _out(service: StandardService, used_by: int = 0) -> ServiceOut:
    return ServiceOut(id=service.id, key=service.key, name=service.name,
                      description=service.description, details=details_of(service),
                      used_by=used_by)


def _uses(db: Session) -> dict[int, int]:
    # Imported here: customer services import this module.
    from app.customer_services import CustomerService

    rows = db.execute(select(CustomerService.standard_service_id, func.count())
                      .group_by(CustomerService.standard_service_id))
    return {service_id: count for service_id, count in rows if service_id is not None}


def _log(db: Session, request: Request, record: UserSession, action: str, service_id: int,
         details: dict[str, object] | None = None) -> None:
    audit.append(db, action, actor_id=record.user.id, actor_name=record.user.username,
                 target_type="standard_service", target_id=str(service_id),
                 ip=client_ip(request), details=details)


def _service(db: Session, service_id: int) -> StandardService:
    service = db.get(StandardService, service_id)
    if service is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That standard service doesn't exist.")
    return service


def _unique_name(db: Session, name: str, service_id: int | None) -> None:
    taken = db.scalar(select(StandardService.id).where(
        func.lower(StandardService.name) == name.casefold()))
    if taken is not None and taken != service_id:
        raise HTTPException(status.HTTP_409_CONFLICT, "There's a standard service with that name.")


@router.get("")
def list_services(_: FullSession, db: DB) -> list[ServiceOut]:
    uses = _uses(db)
    services = db.scalars(select(StandardService).order_by(StandardService.position,
                                                           StandardService.name))
    return [_out(service, uses.get(service.id, 0)) for service in services]


@router.post("")
def add_service(body: ServiceIn, request: Request, keeper: Keeper, db: DB) -> ServiceOut:
    name = body.name.strip()
    _unique_name(db, name, None)
    last = db.scalar(select(func.max(StandardService.position))) or 0
    service = StandardService(
        name=name, description=body.description.strip(), position=last + 1,
        details=json.dumps([d.model_dump() for d in body.details]), created_at=clock.utcnow(),
    )
    db.add(service)
    db.flush()
    _log(db, request, keeper, "service.created", service.id, {"name": name})
    db.commit()
    return _out(service)


@router.put("/{service_id}")
def change_service(service_id: int, body: ServiceIn, request: Request, keeper: Keeper, db: DB
                   ) -> ServiceOut:
    service = _service(db, service_id)
    name = body.name.strip()
    _unique_name(db, name, service.id)
    service.name, service.description = name, body.description.strip()
    service.details = json.dumps([d.model_dump() for d in body.details])
    _log(db, request, keeper, "service.changed", service.id, {"name": name})
    db.commit()
    return _out(service, _uses(db).get(service.id, 0))


@router.delete("/{service_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_service(service_id: int, request: Request, keeper: Keeper, db: DB) -> None:
    """Remove a standard service. Customers' copies stay as they are, with their own
    details, no longer tied to it."""
    service = _service(db, service_id)
    if service.key == "support":
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Support stays: the overview shows each customer's support from it.")
    db.delete(service)
    _log(db, request, keeper, "service.removed", service_id, {"name": service.name})
    db.commit()
