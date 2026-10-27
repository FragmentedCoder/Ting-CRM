"""Security settings Administrators can change (see docs/architecture.md, "Login")."""

from __future__ import annotations

import ipaddress
import json
from dataclasses import asdict, dataclass, fields
from typing import Any

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.db import Base

POLICY_KEY = "security_policy"

# The allowed range of each number, for the admin panel, the wizard and the API alike.
LIMITS: dict[str, tuple[int, int]] = {
    "min_password_length": (8, 64),
    "lockout_threshold": (3, 50),
    "lockout_minutes": (1, 1440),
    "idle_timeout_minutes": (5, 720),
    "max_session_hours": (1, 72),
}


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text)


@dataclass(frozen=True)
class SecurityPolicy:
    min_password_length: int = 12
    # Needs outbound HTTPS to api.pwnedpasswords.com; offline installs turn it off.
    breach_check_enabled: bool = True
    lockout_threshold: int = 10
    lockout_minutes: int = 15
    idle_timeout_minutes: int = 30
    max_session_hours: int = 12
    # Multifactor authentication. Turning either off drops below the OWASP ASVS
    # Level 2 baseline; people who have set up a factor always use it regardless.
    require_mfa_everyone: bool = True
    require_mfa_administrators: bool = True
    # Addresses (CIDR) the admin panel answers from, when switched on.
    admin_allowlist_enabled: bool = False
    admin_allowlist: tuple[str, ...] = ()
    # Addresses anyone may sign in and work from, when switched on.
    login_allowlist_enabled: bool = False
    login_allowlist: tuple[str, ...] = ()
    # Both lists are switched off from the VM console with
    # `ting admin reset-allowlist` if they ever lock everyone out.


def load_policy(db: Session) -> SecurityPolicy:
    stored = db.get(Setting, POLICY_KEY)
    if stored is None:
        return SecurityPolicy()
    raw = json.loads(stored.value)
    known = {field.name for field in fields(SecurityPolicy)}
    values: dict[str, Any] = {k: v for k, v in raw.items() if k in known}
    for name in ("admin_allowlist", "login_allowlist"):
        if name in values:
            values[name] = tuple(values[name])
    # Saved before the switch existed: a non-empty list was in force, so keep it on.
    if "admin_allowlist_enabled" not in raw and raw.get("admin_allowlist"):
        values["admin_allowlist_enabled"] = True
    return SecurityPolicy(**values)


def save_policy(db: Session, policy: SecurityPolicy) -> None:
    db.merge(Setting(key=POLICY_KEY, value=json.dumps(asdict(policy))))


def normalize_networks(entries: list[str]) -> tuple[str, ...]:
    """Parse CIDR ranges (a bare address counts as a single host). Raises ValueError."""
    return tuple(str(ipaddress.ip_network(entry.strip(), strict=False)) for entry in entries)


def _in_networks(ip: str | None, networks: tuple[str, ...]) -> bool:
    if ip is None:
        return False
    try:
        address = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any(address in ipaddress.ip_network(net) for net in networks)


def admin_allowed_from(policy: SecurityPolicy, ip: str | None) -> bool:
    return not policy.admin_allowlist_enabled or _in_networks(ip, policy.admin_allowlist)


def login_allowed_from(policy: SecurityPolicy, ip: str | None) -> bool:
    return not policy.login_allowlist_enabled or _in_networks(ip, policy.login_allowlist)
