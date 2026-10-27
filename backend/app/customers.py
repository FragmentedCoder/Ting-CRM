"""Customers: the records everything else hangs off (see docs/architecture.md).

A customer is a sealed container. It gets its own 256-bit key when it's created,
kept wrapped by the master key and bound to the customer's ID, and everything
that says anything about the customer is sealed with it (app/crypto/sealing.py):
its name, CVR and address, its sites and contacts, its projects' names and dates,
and later its reports and files. Only IDs, project numbers and what access needs
(assignments, classification) stay plain. The audit log names customers by ID.
Deleting a customer deletes its key with it, so nothing sealed with it can be
read again (crypto-shredding).

Who sees which customers follows the spec's access table: Administrators and
Managers all of them, technicians and reviewers the ones they're assigned to,
report designers every name (to attach styles) and auditors every customer's
metadata.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from sqlalchemy import Boolean, ForeignKey, LargeBinary, String, false, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.crypto.keys import generate_key, load_master_key, unwrap_key, wrap_key
from app.crypto.sealing import seal, unseal
from app.db import Base, UTCDateTime
from app.roles import Capability, Role, can
from app.settings import settings

Visibility = Literal["full", "metadata", "names"]

# The spec's "See customers" row. Assigned means full sight of the customers the
# person is assigned to, and nothing of the others.
SEES_CUSTOMERS: dict[Role, Literal["all", "assigned", "metadata", "names"]] = {
    Role.ADMINISTRATOR: "all",
    Role.MANAGER: "all",
    Role.TECHNICIAN: "assigned",
    Role.REVIEWER: "assigned",
    Role.AUDITOR: "metadata",
    Role.REPORT_DESIGNER: "names",
}

LANGUAGES = ("da", "en")


class Customer(Base):
    __tablename__ = "customers"
    # IDs appear in the audit log and in what keys are bound to: never reused.
    __table_args__ = {"sqlite_autoincrement": True}

    id: Mapped[int] = mapped_column(primary_key=True)
    # The customer's own key, wrapped by the master key.
    wrapped_key: Mapped[bytes] = mapped_column(LargeBinary)
    # {"name", "cvr", "address"}, sealed with the customer's key.
    sealed: Mapped[bytes] = mapped_column(LargeBinary)
    language: Mapped[str] = mapped_column(String(5))
    # How long raw data is kept after a project is archived.
    retention_months: Mapped[int]
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class CustomerSite(Base):
    __tablename__ = "customer_sites"
    __table_args__ = {"sqlite_autoincrement": True}

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), index=True
    )
    # {"name", "address"}
    sealed: Mapped[bytes] = mapped_column(LargeBinary)


class CustomerContact(Base):
    __tablename__ = "customer_contacts"
    __table_args__ = {"sqlite_autoincrement": True}

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), index=True
    )
    # {"name", "role", "email", "phone"}: all of it is personal data.
    sealed: Mapped[bytes] = mapped_column(LargeBinary)


class CustomerAssignment(Base):
    __tablename__ = "customer_assignments"

    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    assigned_at: Mapped[datetime] = mapped_column(UTCDateTime)
    assigned_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    # What they're assigned as. Someone with both roles can be a technician for one
    # customer and its reviewer for another, or both; at least one is set.
    as_technician: Mapped[bool] = mapped_column(Boolean, server_default=false())
    as_reviewer: Mapped[bool] = mapped_column(Boolean, server_default=false())

    def capacities(self) -> list[Role]:
        return [role for role, held in ((Role.TECHNICIAN, self.as_technician),
                                        (Role.REVIEWER, self.as_reviewer)) if held]


# Keys and sealing


def customer_key_context(customer_id: int) -> bytes:
    return f"ting/customer-key/{customer_id}".encode()


def bound_to(customer_id: int, kind: str, record_id: int) -> bytes:
    return f"ting/customer/{customer_id}/{kind}/{record_id}".encode()


class Sealer:
    """Seals and opens one customer's records with its key."""

    def __init__(self, customer_id: int, key: bytes) -> None:
        self.customer_id = customer_id
        self._key = key

    def seal(self, kind: str, record_id: int, value: dict[str, Any]) -> bytes:
        return seal(self._key, value, bound_to=bound_to(self.customer_id, kind, record_id))

    def open(self, kind: str, record_id: int, sealed: bytes) -> dict[str, Any]:
        return unseal(self._key, sealed, bound_to=bound_to(self.customer_id, kind, record_id))


class Keyring:
    """Customer keys for one request: the master key is read once, and each
    customer's key unwrapped once however many of its records are opened."""

    def __init__(self) -> None:
        self._master: bytes | None = None
        self._sealers: dict[int, Sealer] = {}

    def _master_key(self) -> bytes:
        if self._master is None:
            self._master = load_master_key(settings.master_key_path)
        return self._master

    def sealer(self, customer: Customer) -> Sealer:
        if customer.id not in self._sealers:
            key = unwrap_key(self._master_key(), customer.wrapped_key,
                             context=customer_key_context(customer.id))
            self._sealers[customer.id] = Sealer(customer.id, key)
        return self._sealers[customer.id]

    def give_new_key(self, customer: Customer) -> Sealer:
        """Make a new customer's key (it needs the ID: flush first)."""
        key = generate_key()
        customer.wrapped_key = wrap_key(self._master_key(), key,
                                        context=customer_key_context(customer.id))
        self._sealers[customer.id] = Sealer(customer.id, key)
        return self._sealers[customer.id]

    def details(self, customer: Customer) -> dict[str, Any]:
        """The customer's sealed name, CVR and address."""
        return self.sealer(customer).open("customer", customer.id, customer.sealed)

    def name(self, customer: Customer) -> str:
        return str(self.details(customer)["name"])


# Who sees what


def is_assigned(db: Session, user_id: int, customer_id: int) -> bool:
    return db.get(CustomerAssignment, (customer_id, user_id)) is not None


def assigned_as(db: Session, user_id: int, customer_id: int, role: Role) -> bool:
    """Whether someone is assigned to a customer as its technician or reviewer."""
    held = db.get(CustomerAssignment, (customer_id, user_id))
    return held is not None and role in held.capacities()


def assigned_customer_ids(db: Session, user_id: int) -> set[int]:
    return set(db.scalars(
        select(CustomerAssignment.customer_id).where(CustomerAssignment.user_id == user_id)
    ))


def sights(roles: set[Role]) -> set[str]:
    return {SEES_CUSTOMERS[role] for role in roles}


def level_for(sight: set[str], assigned: bool) -> Visibility | None:
    """How much of a customer someone with these sights sees."""
    if "all" in sight or ("assigned" in sight and assigned):
        return "full"
    if "metadata" in sight:
        return "metadata"
    if "names" in sight:
        return "names"
    return None


def visibility(db: Session, user_id: int, roles: set[Role], customer_id: int) -> Visibility | None:
    """How much of one customer this person may see, if anything."""
    return level_for(sights(roles), is_assigned(db, user_id, customer_id))


def may_manage(roles: set[Role]) -> bool:
    return can(roles, Capability.MANAGE_CUSTOMERS)


def may_delete(roles: set[Role]) -> bool:
    return can(roles, Capability.DELETE_CUSTOMERS)


def may_manage_projects(roles: set[Role]) -> bool:
    """Create, change, archive and reopen projects, and choose who works on them:
    Administrators and Managers, who see every customer. Technicians and reviewers
    work in the projects they're on."""
    return can(roles, Capability.MANAGE_PROJECTS)
