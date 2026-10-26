"""Multifactor authentication: authenticator apps (TOTP), passkeys and keys, recovery codes."""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta
from typing import Literal

import pyotp
from sqlalchemy import ForeignKey, LargeBinary, String, delete, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from app import clock
from app.auth.sessions import UserSession, rotate_token
from app.db import Base, UTCDateTime
from app.policy import SecurityPolicy
from app.roles import Role, roles_of
from app.users import User

TOTP_PERIOD_SECONDS = 30
TOTP_ISSUER = "Þing"
RECOVERY_CODE_COUNT = 10
# No 0/o, 1/l/i: codes get read off paper.
RECOVERY_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"
RECOVERY_CODE_LENGTH = 12

SecondFactorState = Literal["enrol", "verify", "done"]
Method = Literal["totp", "webauthn", "recovery_code"]


class MfaFactor(Base):
    __tablename__ = "mfa_factors"
    __table_args__ = {"sqlite_autoincrement": True}

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(20))  # "totp" or "webauthn"
    label: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    # None while enrolment is unfinished; such a factor never counts.
    confirmed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_used_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    totp_secret: Mapped[str | None] = mapped_column(String(64))
    # The last time step accepted, so a code can't be used twice.
    totp_last_step: Mapped[int | None]
    credential_id: Mapped[bytes | None] = mapped_column(LargeBinary, unique=True)
    public_key: Mapped[bytes | None] = mapped_column(LargeBinary)
    sign_count: Mapped[int | None]
    transports: Mapped[str | None] = mapped_column(String(200))


class RecoveryCode(Base):
    __tablename__ = "recovery_codes"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    salt: Mapped[bytes] = mapped_column(LargeBinary)
    code_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    used_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


def confirmed_factors(db: Session, user_id: int) -> list[MfaFactor]:
    return list(
        db.scalars(
            select(MfaFactor)
            .where(MfaFactor.user_id == user_id, MfaFactor.confirmed_at.is_not(None))
            .order_by(MfaFactor.id)
        )
    )


def unused_recovery_codes(db: Session, user_id: int) -> list[RecoveryCode]:
    return list(
        db.scalars(
            select(RecoveryCode).where(
                RecoveryCode.user_id == user_id, RecoveryCode.used_at.is_(None)
            )
        )
    )


def mfa_required(db: Session, user_id: int, policy: SecurityPolicy) -> bool:
    if policy.require_mfa_everyone:
        return True
    user = db.get(User, user_id)
    if user is not None and user.is_break_glass:
        return True  # the last way in when everything else fails: always protected
    return policy.require_mfa_administrators and Role.ADMINISTRATOR in roles_of(db, user_id)


def methods_of(db: Session, user_id: int) -> list[Method]:
    """The ways this person can confirm it's them.

    A recovery code is always offered once any factor exists, used up or not:
    leaving it out would tell an attacker the codes are gone.
    """
    kinds = {factor.kind for factor in confirmed_factors(db, user_id)}
    methods: list[Method] = []
    if "totp" in kinds:
        methods.append("totp")
    if "webauthn" in kinds:
        methods.append("webauthn")
    if kinds:
        methods.append("recovery_code")
    return methods


def second_factor_state(
    db: Session, record: UserSession, policy: SecurityPolicy
) -> SecondFactorState:
    """Where the session stands.

    Someone with a factor always uses it. Someone without one sets one up if
    multifactor is required for them, and otherwise is signed in already.
    """
    if record.mfa_verified_at is not None:
        return "done"
    if confirmed_factors(db, record.user_id):
        return "verify"
    return "enrol" if mfa_required(db, record.user_id, policy) else "done"


def may_enrol(db: Session, record: UserSession) -> bool:
    """A new factor needs both factors passed first, unless the account has none yet.

    Otherwise someone holding only the password could add their own factor. A
    temporary password must be replaced before any factor is set up.
    """
    if record.user.must_change_password:
        return False
    return record.mfa_verified_at is not None or not confirmed_factors(db, record.user_id)


def mark_signed_in(record: UserSession) -> None:
    """Bookkeeping for a complete sign-in (or a fresh confirmation, for step-up)."""
    now = clock.utcnow()
    record.confirmed_at = now
    record.user.last_sign_in_at = now
    record.last_seen_at = now
    # Only a complete sign-in resets the failure count; a password alone would let
    # someone guess codes forever, a few at a time between sign-ins.
    record.user.failed_sign_ins = 0
    record.user.locked_until = None


def upgrade_session(db: Session, record: UserSession) -> str:
    """Mark the session as having passed multifactor authentication, under a new token.

    The new token means a token planted or seen before this point (session
    fixation) is worthless. Returns the new token for the cookie.
    """
    token = rotate_token(record)
    record.mfa_verified_at = clock.utcnow()
    record.challenge = None
    record.challenge_purpose = None
    record.challenge_expires_at = None
    mark_signed_in(record)
    return token


def record_second_factor_failure(
    db: Session, record: UserSession, policy: SecurityPolicy
) -> bool:
    """Count a wrong code against the same lockout as wrong passwords.

    Returns True if this failure locked the account; the session is then deleted.
    """
    user = record.user
    db.refresh(user)
    user.failed_sign_ins += 1
    if user.failed_sign_ins < policy.lockout_threshold:
        return False
    user.locked_until = clock.utcnow() + timedelta(minutes=policy.lockout_minutes)
    user.failed_sign_ins = 0
    db.delete(record)
    return True


# Authenticator apps (TOTP, RFC 6238: SHA-1, 6 digits, 30 seconds — what every app supports)


def begin_totp(db: Session, record: UserSession) -> tuple[str, str]:
    """Start enrolling an authenticator app.

    Returns the secret and an otpauth:// link to show as a QR code.
    """
    user = record.user
    db.execute(
        delete(MfaFactor).where(
            MfaFactor.user_id == user.id,
            MfaFactor.kind == "totp",
            MfaFactor.confirmed_at.is_(None),
        )
    )
    secret = pyotp.random_base32(length=32)  # 160 bits, as RFC 4226 recommends
    db.add(
        MfaFactor(
            user_id=user.id,
            kind="totp",
            label="Authenticator app",
            created_at=clock.utcnow(),
            totp_secret=secret,
        )
    )
    uri = pyotp.TOTP(secret).provisioning_uri(name=user.username, issuer_name=TOTP_ISSUER)
    return secret, uri


def _matching_step(factor: MfaFactor, code: str) -> int | None:
    code = code.replace(" ", "")
    if factor.totp_secret is None or len(code) != 6 or not (code.isascii() and code.isdigit()):
        return None
    totp = pyotp.TOTP(factor.totp_secret)
    current = int(clock.utcnow().timestamp()) // TOTP_PERIOD_SECONDS
    last = factor.totp_last_step if factor.totp_last_step is not None else -1
    # One step either side allows for a phone clock that is a little off.
    for step in (current - 1, current, current + 1):
        if step > last and hmac.compare_digest(totp.generate_otp(step), code):
            return step
    return None


def confirm_totp(db: Session, record: UserSession, code: str, label: str) -> MfaFactor | None:
    """Finish enrolling: the first code from the app proves it holds the secret."""
    pending = db.scalar(
        select(MfaFactor).where(
            MfaFactor.user_id == record.user_id,
            MfaFactor.kind == "totp",
            MfaFactor.confirmed_at.is_(None),
        )
    )
    if pending is None:
        return None
    step = _matching_step(pending, code)
    if step is None:
        return None
    now = clock.utcnow()
    pending.confirmed_at = now
    pending.last_used_at = now
    pending.totp_last_step = step
    pending.label = label
    return pending


def verify_totp(db: Session, record: UserSession, code: str) -> MfaFactor | None:
    for factor in confirmed_factors(db, record.user_id):
        if factor.kind != "totp":
            continue
        step = _matching_step(factor, code)
        if step is not None:
            factor.totp_last_step = step
            factor.last_used_at = clock.utcnow()
            return factor
    return None


# Recovery codes: ten one-time codes, shown once, kept only as salted hashes.
# About 60 bits each, so a salted SHA-256 is enough (ASVS 6.6, lookup secrets).


def _normalize_code(code: str) -> str:
    return code.lower().replace("-", "").replace(" ", "")


def _hash_code(salt: bytes, code: str) -> str:
    return hashlib.sha256(salt + code.encode()).hexdigest()


def issue_recovery_codes(db: Session, user_id: int) -> list[str]:
    """Replace the user's recovery codes with ten new ones and return them for showing once."""
    db.execute(delete(RecoveryCode).where(RecoveryCode.user_id == user_id))
    now = clock.utcnow()
    codes = []
    for _ in range(RECOVERY_CODE_COUNT):
        raw = "".join(secrets.choice(RECOVERY_ALPHABET) for _ in range(RECOVERY_CODE_LENGTH))
        salt = os.urandom(16)
        code_hash = _hash_code(salt, raw)
        db.add(RecoveryCode(user_id=user_id, salt=salt, code_hash=code_hash, created_at=now))
        codes.append(f"{raw[:4]}-{raw[4:8]}-{raw[8:]}")
    return codes


def use_recovery_code(db: Session, user_id: int, code: str) -> int | None:
    """Spend a matching code. Returns how many unused codes remain, or None if none matched."""
    normalized = _normalize_code(code)
    unused = unused_recovery_codes(db, user_id)
    match = None
    for candidate in unused:  # check them all, so timing doesn't tell which one matched
        if hmac.compare_digest(candidate.code_hash, _hash_code(candidate.salt, normalized)):
            match = candidate
    if match is None:
        return None
    match.used_at = clock.utcnow()
    return len(unused) - 1
