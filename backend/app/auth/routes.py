from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import audit, clock
from app.auth.dependencies import (
    DB,
    AnySession,
    client_ip,
    effective_capabilities,
    refuse,
)
from app.auth.mfa import (
    Method,
    SecondFactorState,
    has_reusable_code,
    mark_signed_in,
    methods_of,
    second_factor_state,
    unused_recovery_codes,
)
from app.auth.sessions import (
    COOKIE_NAME,
    UserSession,
    check_session,
    csrf_token_for,
    ended_message,
    idle_deadline,
    start_session,
)
from app.auth.sign_in import (
    ADDRESS_WINDOW,
    FAILED_ACTION,
    authenticate,
    too_many_failures_from,
)
from app.images import avatar_url
from app.notices import notify_administrators
from app.policy import load_policy, login_allowed_from
from app.roles import Capability, Role, roles_of
from app.version import ting_version

router = APIRouter(prefix="/auth")

SIGN_IN_FAILED = (
    "Sign-in failed. Check your username and password, or wait a few minutes and try again."
)


class SignInRequest(BaseModel):
    username: str = Field(min_length=1, max_length=150)
    password: str = Field(min_length=1, max_length=1024)


class Colours(BaseModel):
    # None follows the site's colours.
    primary: str | None
    accent: str | None


class UserInfo(BaseModel):
    id: int
    username: str
    display_name: str
    theme: str
    colours: Colours
    avatar_url: str | None
    roles: list[Role]
    # What the roles allow from this address, worked out here so the frontend never
    # re-derives it. "administer" is left out outside the admin IP allowlist.
    capabilities: list[Capability]


class SessionInfo(BaseModel):
    user: UserInfo
    # enrol: set up multifactor now. verify: use one of `methods`. done: signed in.
    second_factor: SecondFactorState
    # The ways this person can confirm it's them, for sign-in and for step-up.
    methods: list[Method]
    # A temporary password must be replaced before the app opens.
    password_change_required: bool
    # Only once signed in: how many recovery codes are left, to warn when few (never
    # for a reusable one).
    recovery_codes_left: int | None
    recovery_code_reusable: bool = False
    csrf_token: str
    idle_expires_at: datetime
    expires_at: datetime
    # Only once signed in: which Þing this is, shown in the menu.
    version: str | None


class SessionStatus(BaseModel):
    idle_expires_at: datetime
    expires_at: datetime


def session_info(db: Session, record: UserSession, token: str, request: Request) -> SessionInfo:
    policy = load_policy(db)
    state = second_factor_state(db, record, policy)
    user = record.user
    return SessionInfo(
        user=UserInfo(
            id=user.id,
            username=user.username,
            display_name=user.display_name,
            theme=user.theme,
            colours=Colours(primary=user.primary_colour, accent=user.accent_colour),
            avatar_url=avatar_url(db, user.id),
            roles=sorted(roles_of(db, user.id)),
            capabilities=sorted(effective_capabilities(db, record, request)),
        ),
        second_factor=state,
        methods=methods_of(db, user.id),
        password_change_required=user.must_change_password,
        recovery_codes_left=(
            len(unused_recovery_codes(db, user.id))
            if state == "done" and methods_of(db, user.id) else None
        ),
        recovery_code_reusable=has_reusable_code(db, user.id),
        csrf_token=csrf_token_for(token),
        idle_expires_at=idle_deadline(record, policy),
        expires_at=record.expires_at,
        version=ting_version() if state == "done" else None,
    )


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        COOKIE_NAME, token, httponly=True, secure=True, samesite="strict", path="/"
    )


@router.post("/sign-in")
def sign_in(body: SignInRequest, request: Request, response: Response, db: DB) -> SessionInfo:
    ip = client_ip(request)
    policy = load_policy(db)
    if not login_allowed_from(policy, ip):
        audit.append(db, "auth.sign_in.refused_network", ip=ip)
        db.commit()
        raise refuse(status.HTTP_403_FORBIDDEN, "Þing isn't available from this network.",
                     "network")
    if too_many_failures_from(db, ip):
        audit.append(db, "auth.sign_in.throttled", ip=ip)
        db.commit()
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Too many sign-in attempts from this computer. Try again in 15 minutes.",
            headers={"Retry-After": str(int(ADDRESS_WINDOW.total_seconds()))},
        )

    outcome = authenticate(db, body.username, body.password, policy)
    account = outcome.account
    actor_id = account.id if account else None
    actor_name = account.username if account else None

    if not outcome.ok or account is None:
        # The typed username is not logged for unknown accounts: people type
        # passwords into the username field.
        audit.append(
            db, FAILED_ACTION, actor_id=actor_id, actor_name=actor_name, ip=ip,
            details={"reason": outcome.reason},
        )
        if outcome.locked_now:
            audit.append(
                db, "auth.account.locked", actor_id=actor_id, actor_name=actor_name, ip=ip,
                details={"minutes": policy.lockout_minutes},
            )
        db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, SIGN_IN_FAILED)

    token, record = start_session(
        db, account, policy, ip=ip, user_agent=request.headers.get("user-agent")
    )
    # Without multifactor required or set up, the password completes the sign-in.
    if second_factor_state(db, record, policy) == "done":
        mark_signed_in(record)
    details: dict[str, object] = {"session": record.id}
    if account.is_break_glass:
        details["break_glass"] = True
        notify_administrators(db, f"Break-glass sign-in to Þing: {account.username}", (
            f"Someone signed in to the break-glass account {account.username} with its "
            f"password, from {ip}, at {clock.utcnow():%Y-%m-%dT%H:%M:%SZ}.\n\n"
            "It's for setup and emergencies. If none of you used it, change its password "
            "and look at the audit log."))
    audit.append(
        db, "auth.sign_in.succeeded", actor_id=actor_id, actor_name=actor_name, ip=ip,
        details=details,
    )
    db.commit()
    set_session_cookie(response, token)
    return session_info(db, record, token, request)


@router.get("/session")
def get_current_session(request: Request, record: AnySession, db: DB) -> SessionInfo:
    return session_info(db, record, request.cookies[COOKIE_NAME], request)


@router.get("/session/status")
def get_session_status(request: Request, db: DB) -> SessionStatus:
    """Is the session still alive? Doesn't count as activity, so the browser can ask
    on a timer and go to the sign-in page the moment the session ends."""
    token = request.cookies.get(COOKIE_NAME)
    policy = load_policy(db)
    if not token:
        raise refuse(status.HTTP_401_UNAUTHORIZED, "Sign in to continue.", "signed_out")
    record, reason = check_session(db, token, policy, ip=client_ip(request), touch=False)
    db.commit()
    if record is None:
        raise refuse(status.HTTP_401_UNAUTHORIZED, ended_message(reason or "", policy),
                     f"session_{reason}")
    return SessionStatus(idle_expires_at=idle_deadline(record, policy),
                         expires_at=record.expires_at)


@router.post("/sign-out", status_code=status.HTTP_204_NO_CONTENT)
def sign_out(request: Request, response: Response, record: AnySession, db: DB) -> None:
    audit.append(
        db,
        "auth.sign_out",
        actor_id=record.user.id,
        actor_name=record.user.username,
        ip=client_ip(request),
        details={"session": record.id},
    )
    db.delete(record)
    db.commit()
    response.delete_cookie(COOKIE_NAME, path="/", secure=True, httponly=True, samesite="strict")
