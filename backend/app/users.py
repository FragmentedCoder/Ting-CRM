from __future__ import annotations

import secrets
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import LargeBinary, String, false, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from app import clock
from app.auth import pwned
from app.auth.passwords import (
    PasswordRejected,
    check_password,
    hash_password,
    normalize_password,
)
from app.db import Base, UTCDateTime
from app.policy import SecurityPolicy

TEMPORARY_PASSWORD_DAYS = 7
TEMPORARY_PASSWORD_LENGTH = 16
# No 0/o, 1/l/i: temporary passwords get read out or typed from a note.
TEMPORARY_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"
THEMES = ("system", "light", "dark")


class User(Base):
    __tablename__ = "users"
    # IDs appear in the audit log, so one must never be reused for someone else.
    __table_args__ = {"sqlite_autoincrement": True}

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(150), unique=True)
    display_name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str | None] = mapped_column(String(254))
    # Work details colleagues see beside their name. Nothing private.
    first_name: Mapped[str | None] = mapped_column(String(100))
    middle_name: Mapped[str | None] = mapped_column(String(100))
    last_name: Mapped[str | None] = mapped_column(String(100))
    job_title: Mapped[str | None] = mapped_column(String(150))
    department: Mapped[str | None] = mapped_column(String(150))
    phone: Mapped[str | None] = mapped_column(String(50))
    # None for accounts that sign in through a directory (release 1.2), never locally.
    password_hash: Mapped[str | None] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(default=True)
    # The setup wizard's local Administrator, for when the directory is down. Every
    # use is flagged in the audit log.
    is_break_glass: Mapped[bool] = mapped_column(default=False, server_default=false())
    failed_sign_ins: Mapped[int] = mapped_column(default=0)
    locked_until: Mapped[datetime | None] = mapped_column(UTCDateTime)
    password_changed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    # Set for a temporary password an Administrator handed out: it works once, to
    # choose a real one, and only until password_expires_at.
    must_change_password: Mapped[bool] = mapped_column(default=False, server_default=false())
    password_expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_sign_in_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    theme: Mapped[str] = mapped_column(String(10), default="system", server_default="system")
    # The person's own colours; None follows the site's (see app/colours.py).
    primary_colour: Mapped[str | None] = mapped_column(String(20))
    accent_colour: Mapped[str | None] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    # Random, not the user id: passkeys store it, and it shouldn't identify anyone.
    webauthn_handle: Mapped[bytes | None] = mapped_column(LargeBinary, unique=True, index=True)


def normalize_username(username: str) -> str:
    return unicodedata.normalize("NFKC", username).strip().casefold()


def find_user(db: Session, username: str) -> User | None:
    return db.scalar(select(User).where(User.username == normalize_username(username)))


@dataclass(frozen=True)
class NewPassword:
    """A password that passed every rule, the breach check included.

    Only vet_new_password makes these, and create_user takes nothing else, so a
    code path can't set a password without the checks.
    """

    value: str = field(repr=False)
    username: str


def vet_new_password(password: str, policy: SecurityPolicy, *, username: str) -> NewPassword:
    """Check a new password against every rule.

    Makes a network call when the breach check is on, so call it outside any
    database transaction. Raises PasswordRejected, or pwned.BreachCheckUnavailable
    when the breach check can't be reached.
    """
    username = normalize_username(username)
    check_password(password, policy, username=username)
    if policy.breach_check_enabled and pwned.times_breached(normalize_password(password)):
        raise PasswordRejected(
            "This password has appeared in a data breach, so attackers try it early. "
            "Choose another."
        )
    return NewPassword(password, username)


def temporary_password(policy: SecurityPolicy, *, username: str) -> NewPassword:
    """A random one-time password for an Administrator to hand over.

    ASVS 6.4: it must be random, expire soon, and be replaced at first use. Being
    random, it needs no breach check.
    """
    username = normalize_username(username)
    length = max(TEMPORARY_PASSWORD_LENGTH, policy.min_password_length)
    while True:
        raw = "".join(secrets.choice(TEMPORARY_ALPHABET) for _ in range(length))
        value = "-".join(raw[i : i + 4] for i in range(0, length, 4))
        try:
            check_password(value, policy, username=username)
        except PasswordRejected:
            continue  # it happened to contain the username: draw again
        return NewPassword(value, username)


def _apply_password(user: User, hashed: str, *, temporary: bool) -> None:
    now = clock.utcnow()
    user.password_hash = hashed
    user.password_changed_at = now
    user.must_change_password = temporary
    user.password_expires_at = now + timedelta(days=TEMPORARY_PASSWORD_DAYS) if temporary else None
    user.failed_sign_ins = 0
    user.locked_until = None


def set_password(db: Session, user: User, password: NewPassword, *, temporary: bool) -> None:
    """Give an existing user a new password.

    Commits the caller's transaction first and hashes outside one: Argon2 takes
    about 0.1 s, and an open transaction holds the database's write lock.
    """
    if password.username != user.username:
        raise ValueError("The password was vetted for a different username.")
    db.commit()
    hashed = hash_password(password.value)
    db.refresh(user)
    _apply_password(user, hashed, temporary=temporary)


def create_user(
    db: Session,
    username: str,
    display_name: str,
    password: NewPassword,
    *,
    email: str | None = None,
    is_break_glass: bool = False,
    temporary: bool = False,
) -> User:
    """Callers write the audit entry."""
    username = normalize_username(username)
    if password.username != username:
        raise ValueError("The password was vetted for a different username.")
    hashed = hash_password(password.value)
    user = User(
        username=username,
        display_name=display_name.strip(),
        email=email,
        is_active=True,
        is_break_glass=is_break_glass,
        created_at=clock.utcnow(),
    )
    _apply_password(user, hashed, temporary=temporary)
    db.add(user)
    db.flush()
    return user
