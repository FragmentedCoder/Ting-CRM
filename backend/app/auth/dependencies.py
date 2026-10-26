from __future__ import annotations

import hmac
from collections.abc import Callable
from datetime import timedelta
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app import audit, clock
from app.auth.mfa import second_factor_state
from app.auth.sessions import (
    COOKIE_NAME,
    UserSession,
    check_session,
    csrf_token_for,
    ended_message,
)
from app.db import get_db
from app.policy import admin_allowed_from, load_policy
from app.roles import Capability, Role, can, roles_of

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
CSRF_HEADER = "X-CSRF-Token"
# Why a request was refused, for the frontend to act on (sign in again, finish
# multifactor, confirm it's you); the detail text is for people.
REASON_HEADER = "X-Ting-Reason"
STEP_UP_WINDOW = timedelta(minutes=5)
# What the admin panel shows. Outside the admin IP allowlist the Administrator role
# opens none of it.
ADMIN_PANEL = frozenset({Capability.ADMINISTER, Capability.READ_AUDIT_LOG})

DB = Annotated[Session, Depends(get_db)]


def refuse(status_code: int, message: str, reason: str) -> HTTPException:
    return HTTPException(status_code, message, headers={REASON_HEADER: reason})


def client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def current_session(request: Request, db: DB) -> UserSession:
    """Any live session, including one still waiting for multifactor authentication."""
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise refuse(status.HTTP_401_UNAUTHORIZED, "Sign in to continue.", "signed_out")
    policy = load_policy(db)
    record, reason = check_session(db, token, policy, ip=client_ip(request))
    db.commit()
    if record is None:
        raise refuse(
            status.HTTP_401_UNAUTHORIZED, ended_message(reason or "", policy), f"session_{reason}"
        )
    if request.method not in SAFE_METHODS:
        sent = request.headers.get(CSRF_HEADER, "")
        if not hmac.compare_digest(sent, csrf_token_for(token)):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "The request could not be verified. Reload the page and try again.",
            )
    return record


AnySession = Annotated[UserSession, Depends(current_session)]


def require_full_session(record: AnySession, db: DB) -> UserSession:
    """A completely signed-in session. Every route that touches data depends on this."""
    if second_factor_state(db, record, load_policy(db)) != "done":
        raise refuse(
            status.HTTP_403_FORBIDDEN,
            "Finish signing in with multifactor authentication first.",
            "mfa_required",
        )
    if record.user.must_change_password:
        raise refuse(
            status.HTTP_403_FORBIDDEN, "Choose a new password first.", "password_change_required"
        )
    return record


FullSession = Annotated[UserSession, Depends(require_full_session)]


def require_recent_confirmation(record: UserSession) -> None:
    """Step-up: refuse unless the person proved it's them in the last few minutes."""
    confirmed = record.confirmed_at
    if confirmed is None or clock.utcnow() - confirmed > STEP_UP_WINDOW:
        raise refuse(
            status.HTTP_403_FORBIDDEN,
            "Confirm it's you again before changing security settings.",
            "step_up_required",
        )


def require_step_up(
    record: UserSession, message: str = "Confirm it's you to lower security settings."
) -> None:
    """Refuse unless the person confirmed it's them just now, for this change.

    Signing in doesn't count, and the confirmation is used up: lowering security
    asks every time. The caller commits it with the change.
    """
    confirmed = record.step_up_at
    if confirmed is None or clock.utcnow() - confirmed > STEP_UP_WINDOW:
        raise refuse(status.HTTP_403_FORBIDDEN, message, "step_up_required")
    record.step_up_at = None


def effective_capabilities(
    db: Session, record: UserSession, request: Request
) -> set[Capability]:
    """What the roles allow from where this request comes from.

    Outside the admin IP allowlist, the Administrator role grants nothing in the
    admin panel, so its link disappears; everything else, and the same capability
    through another role (an Auditor reading the log), still counts.
    """
    roles = roles_of(db, record.user_id)
    capabilities = {c for c in Capability if can(roles, c)}
    if not admin_allowed_from(load_policy(db), client_ip(request)):
        others = roles - {Role.ADMINISTRATOR}
        capabilities -= {c for c in ADMIN_PANEL if not can(others, c)}
    return capabilities


def require(capability: Capability) -> Callable[..., UserSession]:
    """A dependency that lets through only signed-in users whose roles grant capability.

    The admin panel (ADMINISTER) also answers only from the admin IP allowlist.
    """

    def check(request: Request, record: FullSession, db: DB) -> UserSession:
        if capability in effective_capabilities(db, record, request):
            return record
        outside = can(roles_of(db, record.user_id), capability)
        audit.append(
            db,
            "auth.access_denied",
            actor_id=record.user.id,
            actor_name=record.user.username,
            ip=client_ip(request),
            details={"capability": capability.value, "path": request.url.path},
        )
        db.commit()
        if outside:
            raise refuse(status.HTTP_403_FORBIDDEN,
                         "The admin panel isn't available from this address.", "network")
        raise refuse(status.HTTP_403_FORBIDDEN, "You don't have access to this.", "forbidden")

    return check
