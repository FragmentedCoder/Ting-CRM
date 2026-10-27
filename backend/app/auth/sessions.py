"""Server-side sessions. The browser holds a random token; the database holds only its hash."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta

from sqlalchemy import ForeignKey, LargeBinary, Select, String, delete, select, update
from sqlalchemy.orm import Mapped, Session, mapped_column, relationship

from app import clock
from app.db import Base, UTCDateTime
from app.policy import SecurityPolicy, login_allowed_from
from app.users import User

# __Host- makes browsers refuse the cookie unless it is Secure, has Path=/ and no Domain.
COOKIE_NAME = "__Host-ting_session"

# Recording activity on every request would mean a write per request.
TOUCH_INTERVAL = timedelta(minutes=1)


class UserSession(Base):
    __tablename__ = "user_sessions"
    # IDs appear in the audit log, so a new session must never reuse an old one's.
    __table_args__ = {"sqlite_autoincrement": True}

    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    mfa_verified_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    # When the person last proved it's them (multifactor, or the password when they
    # have no factor). Sensitive changes need this to be recent (step-up).
    confirmed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    # When they last confirmed it's them on request, while already signed in. Used
    # up by a change that lowers security, so each such change asks again.
    step_up_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    ip: Mapped[str | None] = mapped_column(String(45))
    user_agent: Mapped[str | None] = mapped_column(String(255))
    # A passkey ceremony in progress: one challenge at a time, used once.
    challenge: Mapped[bytes | None] = mapped_column(LargeBinary)
    challenge_purpose: Mapped[str | None] = mapped_column(String(20))
    challenge_expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    # Set when someone else ends the session (an administrator, a password change).
    # The row stays until the browser comes back, so it can be told why, and
    # nothing can ever revive it.
    ended_reason: Mapped[str | None] = mapped_column(String(20))

    user: Mapped[User] = relationship(lazy="joined")


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def csrf_token_for(token: str) -> str:
    """Derived from the session token, so it needs no storage and dies with the session."""
    return hmac.new(token.encode(), b"ting/csrf", hashlib.sha256).hexdigest()


def start_session(
    db: Session,
    user: User,
    policy: SecurityPolicy,
    *,
    ip: str | None,
    user_agent: str | None,
) -> tuple[str, UserSession]:
    token = secrets.token_urlsafe(32)
    now = clock.utcnow()
    # Sessions whose browser never came back, ended or not, go once they expire.
    db.execute(delete(UserSession).where(UserSession.expires_at < now))
    record = UserSession(
        token_hash=hash_token(token),
        user_id=user.id,
        user=user,
        created_at=now,
        last_seen_at=now,
        expires_at=now + timedelta(hours=policy.max_session_hours),
        ip=ip,
        user_agent=(user_agent or "")[:255] or None,
    )
    db.add(record)
    db.flush()
    return token, record


def rotate_token(record: UserSession) -> str:
    """Give the session a new token, so one seen before this point is worthless.

    Done whenever the session gains rights (multifactor) or the credentials
    behind it change (new password). Returns the new token for the cookie.
    """
    token = secrets.token_urlsafe(32)
    record.token_hash = hash_token(token)
    return token


def live_sessions(user_id: int) -> Select[UserSession]:
    return select(UserSession).where(
        UserSession.user_id == user_id, UserSession.ended_reason.is_(None)
    )


def end_sessions(
    db: Session, user_id: int, reason: str, *, keep: UserSession | None = None
) -> int:
    """Sign a user out everywhere (except `keep`). Returns how many sessions ended.

    reason is what the browser is told next time (see ended_message).
    """
    query = update(UserSession).where(
        UserSession.user_id == user_id, UserSession.ended_reason.is_(None)
    )
    if keep is not None:
        query = query.where(UserSession.id != keep.id)
    result = db.execute(query.values(ended_reason=reason))
    return int(getattr(result, "rowcount", 0) or 0)


def idle_deadline(record: UserSession, policy: SecurityPolicy) -> datetime:
    return record.last_seen_at + timedelta(minutes=policy.idle_timeout_minutes)


def ended_message(reason: str, policy: SecurityPolicy) -> str:
    """What to tell someone whose session ended, in plain words."""
    return {
        "timed_out": f"You were signed out after {policy.idle_timeout_minutes} minutes without "
        "activity. Sign in again to continue.",
        "expired": f"Sessions last at most {policy.max_session_hours} hours. Sign in again to "
        "continue.",
        "disabled": "Your account has been disabled. Ask an administrator if you need access.",
        "network": "Þing isn't available from this network.",
        "by_admin": "An administrator signed you out. Sign in again to continue.",
        "password_reset": "An administrator reset your password. Sign in with the new one.",
        "mfa_reset": "An administrator reset your multifactor authentication. Sign in to set "
        "it up again.",
        "by_you": "You signed this browser out from another one.",
        "password_changed": "Your password was changed in another browser. Sign in with the "
        "new one.",
    }.get(reason, "Your session has ended. Sign in again to continue.")


def _why_ended(record: UserSession, policy: SecurityPolicy, ip: str | None) -> str | None:
    now = clock.utcnow()
    if record.ended_reason is not None:
        return record.ended_reason
    if not record.user.is_active:
        return "disabled"
    if now >= record.expires_at:
        return "expired"
    if now >= idle_deadline(record, policy):
        return "timed_out"
    if not login_allowed_from(policy, ip):
        return "network"
    return None


def check_session(
    db: Session, token: str, policy: SecurityPolicy, *, ip: str | None, touch: bool = True
) -> tuple[UserSession | None, str | None]:
    """The session for token and None, or None and why it ended.

    A session that has ended is deleted on the way, once the browser has been told
    why. With touch=False the check doesn't count as activity, so a browser can
    watch its session without keeping it alive.
    """
    record = db.scalar(select(UserSession).where(UserSession.token_hash == hash_token(token)))
    if record is None:
        return None, "ended"
    reason = _why_ended(record, policy, ip)
    if reason is not None:
        db.delete(record)
        return None, reason
    now = clock.utcnow()
    if touch and now - record.last_seen_at >= TOUCH_INTERVAL:
        record.last_seen_at = now
    return record, None
