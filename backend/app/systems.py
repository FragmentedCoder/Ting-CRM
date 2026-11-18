"""A customer's systems: what they are, what runs on what, and how they're kept.

Each system belongs to one customer and is sealed with its key, like contacts
and sites. A virtual machine names its host (parent_id), in the same customer,
and never itself or a host that runs on it. Its host, the day it was retired and
its warranty end stay plain: warnings and the host tree need them without
opening the customer (see app/customers.py). The routes are in
app/customer_routes.py, beside the customer's other records.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.customers import CustomerSystem, Sealer

Group = Literal["servers", "network", "cloud", "printers", "other"]
SystemType = Literal[
    "physical_server", "virtual_machine", "nas", "backup_server", "firewall", "router",
    "switch", "wireless", "printer", "m365_tenant", "other",
]

# The sealed fields, with what an older record reads as.
SEALED_DEFAULTS: dict[str, Any] = {
    "group": "servers", "type": "physical_server", "name": "", "role": "", "site_id": None,
    "hostname": "", "ip": "", "hardware": "", "serial": "", "os": "", "in_service_since": None,
    "updates_itself": None, "may_update_in_working_hours": None, "update_rhythm": "",
    "last_update": None, "monitoring": "", "backup": "", "notes": "",
}


class SystemIn(BaseModel):
    group: Group = "servers"
    type: SystemType = "physical_server"
    name: str = Field(min_length=1, max_length=100)
    # What it does: "DC and file server", "Booking system".
    role: str = Field(default="", max_length=150)
    site_id: int | None = None
    # The host it runs on, for a virtual machine.
    parent_id: int | None = None
    hostname: str = Field(default="", max_length=253, pattern=r"^[A-Za-z0-9.\-]*$")
    ip: str = Field(default="", max_length=100, pattern=r"^[0-9A-Fa-f:.,/ ]*$")
    hardware: str = Field(default="", max_length=200)
    serial: str = Field(default="", max_length=100)
    os: str = Field(default="", max_length=150)
    in_service_since: date | None = None
    warranty_end: date | None = None
    retired_on: date | None = None
    # Maintenance: None means not known yet.
    updates_itself: bool | None = None
    may_update_in_working_hours: bool | None = None
    update_rhythm: str = Field(default="", max_length=100)
    last_update: date | None = None
    monitoring: str = Field(default="", max_length=300)
    backup: str = Field(default="", max_length=300)
    notes: str = Field(default="", max_length=2000)


class SystemOut(SystemIn):
    id: int


def sealed_fields(body: SystemIn) -> dict[str, Any]:
    plain = {"parent_id", "warranty_end", "retired_on"}
    fields = body.model_dump(mode="json", exclude=plain)
    return {name: value.strip() if isinstance(value, str) else value
            for name, value in fields.items()}


def systems_of(db: Session, sealer: Sealer, customer_id: int) -> list[SystemOut]:
    rows = db.scalars(select(CustomerSystem).where(CustomerSystem.customer_id == customer_id))
    found = [
        SystemOut(id=row.id, parent_id=row.parent_id, warranty_end=row.warranty_end,
                  retired_on=row.retired_on,
                  **(SEALED_DEFAULTS | sealer.open("system", row.id, row.sealed)))
        for row in rows
    ]
    return sorted(found, key=lambda s: s.name.casefold())


def would_loop(db: Session, system_id: int | None, parent_id: int) -> bool:
    """Whether running on parent_id would make a system its own host, somewhere up."""
    seen: set[int] = set()
    current: int | None = parent_id
    while current is not None and current not in seen:
        if current == system_id:
            return True
        seen.add(current)
        host = db.get(CustomerSystem, current)
        current = host.parent_id if host else None
    return False
