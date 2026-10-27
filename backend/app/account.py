"""Your own account: profile, password, multifactor, recovery codes, theme, sessions.

Also the forced password change after an Administrator hands out a temporary
password. Changing what proves who you are (removing a factor, new recovery
codes) asks for your password again; a wrong one counts towards the lockout.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal, NoReturn

from fastapi import APIRouter, Body, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import audit, clock
from app.auth.dependencies import DB, AnySession, FullSession, client_ip, refuse
from app.auth.mfa import (
    confirmed_factors,
    issue_recovery_codes,
    mfa_required,
    unused_recovery_codes,
)
from app.auth.mfa_routes import FactorInfo
from app.auth.passwords import PasswordRejected, verify_password
from app.auth.pwned import BreachCheckUnavailable
from app.auth.routes import SessionInfo, session_info, set_session_cookie
from app.auth.sessions import UserSession, end_sessions, live_sessions, rotate_token
from app.auth.sign_in import record_password_failure
from app.colours import AccentColour, PrimaryColour
from app.images import (
    AVATAR_SIZE,
    IMAGE_HEADERS,
    ImageRejected,
    avatar_key,
    avatar_url,
    clean_image,
    load_image,
    remove_image,
    store_image,
)
from app.policy import load_policy
from app.users import User, set_password, vet_new_password

router = APIRouter()

PROFILE_FIELDS = (
    "display_name", "first_name", "middle_name", "last_name", "job_title", "department",
    "email", "phone",
)


class SessionSummary(BaseModel):
    id: int
    created_at: datetime
    last_seen_at: datetime
    ip: str | None
    user_agent: str | None
    second_factor_done: bool
    current: bool = False


class Profile(BaseModel):
    """Work details colleagues see beside someone's name."""

    display_name: str
    first_name: str | None
    middle_name: str | None
    last_name: str | None
    job_title: str | None
    department: str | None
    email: str | None
    phone: str | None


class ProfileUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=200)
    first_name: str | None = Field(default=None, max_length=100)
    middle_name: str | None = Field(default=None, max_length=100)
    last_name: str | None = Field(default=None, max_length=100)
    job_title: str | None = Field(default=None, max_length=150)
    department: str | None = Field(default=None, max_length=150)
    email: str | None = Field(default=None, max_length=254, pattern=r"^([^@\s]+@[^@\s]+)?$")
    phone: str | None = Field(default=None, max_length=50, pattern=r"^[0-9+()\-. ]*$")


class AccountInfo(Profile):
    username: str
    theme: str
    primary_colour: str | None
    accent_colour: str | None
    avatar_url: str | None
    password_changed_at: datetime | None
    mfa_required: bool
    factors: list[FactorInfo]
    recovery_codes_left: int
    sessions: list[SessionSummary]


class AccountUpdate(ProfileUpdate):
    theme: Literal["system", "light", "dark"] | None = None
    # Sent as null to follow the site's colours again.
    primary_colour: PrimaryColour | None = None
    accent_colour: AccentColour | None = None


class PasswordRules(BaseModel):
    """What a new password must meet, for the help text beside password fields."""

    min_length: int
    breach_check: bool


class NewPasswordRequest(BaseModel):
    new_password: str = Field(min_length=1, max_length=1024)


class PasswordChangeRequest(NewPasswordRequest):
    current_password: str = Field(min_length=1, max_length=1024)


class PasswordConfirmation(BaseModel):
    password: str = Field(min_length=1, max_length=1024)


class RecoveryCodes(BaseModel):
    recovery_codes: list[str]


def profile_of(user: User) -> dict[str, Any]:
    return {name: getattr(user, name) for name in PROFILE_FIELDS}


def apply_profile(user: User, update: ProfileUpdate) -> list[str]:
    """Copy the fields that were sent onto user. Returns the names that changed."""
    changed = []
    for name in update.model_fields_set & set(PROFILE_FIELDS):
        value = getattr(update, name)
        value = value.strip() if isinstance(value, str) else value
        if name != "display_name":
            value = value or None
        elif not value:
            continue
        if getattr(user, name) != value:
            setattr(user, name, value)
            changed.append(name)
    return sorted(changed)


def factor_infos(db: Session, user_id: int) -> list[FactorInfo]:
    return [
        FactorInfo(id=f.id, kind=f.kind, label=f.label, created_at=f.created_at,
                   last_used_at=f.last_used_at)
        for f in confirmed_factors(db, user_id)
    ]


def session_summaries(
    db: Session, user_id: int, current: UserSession | None = None
) -> list[SessionSummary]:
    records = db.scalars(live_sessions(user_id).order_by(UserSession.id))
    return [
        SessionSummary(
            id=r.id, created_at=r.created_at, last_seen_at=r.last_seen_at, ip=r.ip,
            user_agent=r.user_agent, second_factor_done=r.mfa_verified_at is not None,
            current=current is not None and r.id == current.id,
        )
        for r in records
    ]


def _log(
    db: Session, request: Request, record: UserSession, action: str,
    details: dict[str, object] | None = None,
) -> None:
    audit.append(db, action, actor_id=record.user.id, actor_name=record.user.username,
                 ip=client_ip(request), details=details)


def _confirm_password(db: Session, request: Request, record: UserSession, password: str) -> None:
    """Re-check the user's password before a sensitive change. Hashes outside a transaction."""
    policy = load_policy(db)
    user = record.user
    hashed = user.password_hash
    db.commit()
    if hashed is not None and verify_password(hashed, password):
        return
    outcome = record_password_failure(db, user, policy)
    ip = client_ip(request)
    audit.append(db, "auth.password_confirmation.failed", actor_id=user.id,
                 actor_name=user.username, ip=ip)
    if outcome.locked_now:
        audit.append(db, "auth.account.locked", actor_id=user.id, actor_name=user.username,
                     ip=ip, details={"minutes": policy.lockout_minutes})
        db.delete(record)
        db.commit()
        raise refuse(status.HTTP_401_UNAUTHORIZED,
                     "Too many wrong attempts. Sign in again in a few minutes.", "session_locked")
    db.commit()
    raise HTTPException(status.HTTP_400_BAD_REQUEST, "That's not your password.")


def _refuse_password(exc: Exception) -> NoReturn:
    if isinstance(exc, BreachCheckUnavailable):
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Þing couldn't check the new password against known data breaches. Try again "
            "in a moment, or ask an administrator.",
        ) from exc
    raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


def _change_password(
    db: Session, request: Request, response: Response, record: UserSession, new_password: str,
) -> SessionInfo:
    """Set a new password, sign out every other session, and rotate this one's token."""
    policy = load_policy(db)
    user = record.user
    old_hash = user.password_hash
    was_temporary = user.must_change_password
    db.commit()  # the checks below hash and call out to the network
    if old_hash is not None and verify_password(old_hash, new_password):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Choose a password different from your current one."
        )
    try:
        vetted = vet_new_password(new_password, policy, username=user.username)
    except (PasswordRejected, BreachCheckUnavailable) as exc:
        _refuse_password(exc)
    set_password(db, user, vetted, temporary=False)
    ended = end_sessions(db, user.id, "password_changed", keep=record)
    token = rotate_token(record)
    _log(db, request, record, "auth.password.changed",
         {"was_temporary": was_temporary, "other_sessions_ended": ended})
    db.commit()
    set_session_cookie(response, token)
    return session_info(db, record, token, request)


@router.post("/auth/new-password")
def choose_new_password(
    body: NewPasswordRequest, request: Request, response: Response, record: AnySession, db: DB
) -> SessionInfo:
    """Replace a temporary password. If the account has multifactor, that comes first."""
    if not record.user.must_change_password:
        raise HTTPException(status.HTTP_409_CONFLICT, "Your password doesn't need changing.")
    if record.mfa_verified_at is None and confirmed_factors(db, record.user_id):
        raise refuse(status.HTTP_403_FORBIDDEN,
                     "Finish signing in with multifactor authentication first.", "mfa_required")
    return _change_password(db, request, response, record, body.new_password)


@router.post("/auth/confirm-password", status_code=status.HTTP_204_NO_CONTENT)
def confirm_with_password(
    body: PasswordConfirmation, request: Request, record: FullSession, db: DB
) -> None:
    """Step-up for people without multifactor. Anyone who has it must use it instead."""
    if confirmed_factors(db, record.user_id):
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Confirm it's you with multifactor authentication.")
    _confirm_password(db, request, record, body.password)
    record.confirmed_at = record.step_up_at = clock.utcnow()
    _log(db, request, record, "auth.confirmed", {"method": "password"})
    db.commit()


@router.get("/auth/password-rules")
def password_rules(_: AnySession, db: DB) -> PasswordRules:
    policy = load_policy(db)
    return PasswordRules(min_length=policy.min_password_length,
                         breach_check=policy.breach_check_enabled)


@router.get("/account")
def get_account(record: FullSession, db: DB) -> AccountInfo:
    user = record.user
    return AccountInfo(
        **profile_of(user),
        username=user.username,
        theme=user.theme,
        primary_colour=user.primary_colour,
        accent_colour=user.accent_colour,
        avatar_url=avatar_url(db, user.id),
        password_changed_at=user.password_changed_at,
        mfa_required=mfa_required(db, user.id, load_policy(db)),
        factors=factor_infos(db, user.id),
        recovery_codes_left=len(unused_recovery_codes(db, user.id)),
        sessions=session_summaries(db, user.id, current=record),
    )


@router.patch("/account")
def update_account(body: AccountUpdate, request: Request, record: FullSession, db: DB
                   ) -> AccountInfo:
    user = record.user
    changed = apply_profile(user, body)
    # How Þing looks to someone (light or dark, colours, their picture) is theirs
    # alone and isn't logged; their name, email and other details are, since
    # colleagues and notices see them.
    if body.theme and body.theme != user.theme:
        user.theme = body.theme
    for name in ("primary_colour", "accent_colour"):
        if name in body.model_fields_set and getattr(body, name) != getattr(user, name):
            setattr(user, name, getattr(body, name))
    if changed:
        _log(db, request, record, "account.updated", {"fields": sorted(changed)})
    db.commit()
    return get_account(record, db)


@router.put("/account/avatar")
def upload_avatar(
    data: Annotated[bytes, Body(media_type="application/octet-stream")],
    request: Request, record: FullSession, db: DB,
) -> AccountInfo:
    try:
        png = clean_image(data, max_size=AVATAR_SIZE)
    except ImageRejected as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    store_image(db, avatar_key(record.user_id), png)
    db.commit()
    return get_account(record, db)


@router.delete("/account/avatar")
def remove_avatar(request: Request, record: FullSession, db: DB) -> AccountInfo:
    remove_image(db, avatar_key(record.user_id))
    db.commit()
    return get_account(record, db)


@router.get("/users/{user_id}/avatar")
def get_avatar(user_id: int, _: FullSession, db: DB) -> Response:
    image = load_image(db, avatar_key(user_id))
    if image is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No profile picture.")
    return Response(image.data, media_type=image.content_type, headers=IMAGE_HEADERS)


@router.post("/account/password")
def change_my_password(
    body: PasswordChangeRequest, request: Request, response: Response, record: FullSession,
    db: DB,
) -> SessionInfo:
    _confirm_password(db, request, record, body.current_password)
    return _change_password(db, request, response, record, body.new_password)


@router.post("/account/factors/{factor_id}/remove")
def remove_my_factor(
    factor_id: int, body: PasswordConfirmation, request: Request, record: FullSession, db: DB
) -> AccountInfo:
    _confirm_password(db, request, record, body.password)
    factors = confirmed_factors(db, record.user_id)
    factor = next((f for f in factors if f.id == factor_id), None)
    if factor is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That factor doesn't exist.")
    if len(factors) == 1 and mfa_required(db, record.user_id, load_policy(db)):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Your account needs multifactor authentication. Add another factor before "
            "removing this one.",
        )
    db.delete(factor)
    _log(db, request, record, "auth.mfa.removed", {"method": factor.kind, "label": factor.label})
    db.commit()
    return get_account(record, db)


@router.post("/account/recovery-codes")
def new_recovery_codes(
    body: PasswordConfirmation, request: Request, record: FullSession, db: DB
) -> RecoveryCodes:
    _confirm_password(db, request, record, body.password)
    codes = issue_recovery_codes(db, record.user_id)
    _log(db, request, record, "auth.mfa.recovery_codes_issued", {"count": len(codes)})
    db.commit()
    return RecoveryCodes(recovery_codes=codes)


@router.post("/account/sessions/end-others")
def end_my_other_sessions(request: Request, record: FullSession, db: DB) -> AccountInfo:
    ended = end_sessions(db, record.user_id, "by_you", keep=record)
    _log(db, request, record, "auth.sessions.ended", {"count": ended, "by": "self"})
    db.commit()
    return get_account(record, db)


@router.post("/account/sessions/{session_id}/end")
def end_my_session(session_id: int, request: Request, record: FullSession, db: DB
                   ) -> AccountInfo:
    """Sign out one other browser. To sign out this one, use Sign out."""
    other = db.get(UserSession, session_id)
    if (other is None or other.user_id != record.user_id or other.id == record.id
            or other.ended_reason is not None):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That session doesn't exist.")
    other.ended_reason = "by_you"
    _log(db, request, record, "auth.sessions.ended",
         {"count": 1, "by": "self", "session": session_id})
    db.commit()
    return get_account(record, db)
