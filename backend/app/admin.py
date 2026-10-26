"""The admin panel's API: users and their roles, security settings, branding.

Every route needs the ADMINISTER capability, which also enforces the admin IP
allowlist. Guards keep an install from locking itself out: you can't disable
yourself or drop your own Administrator role, the break-glass Administrator
keeps that role and stays active, and an allowlist that leaves out your own
address is refused. Security changes that weaken the policy need the administrator
to confirm it's them for that change (step-up); changes that can sign people out
need a recent confirmation.
"""

from __future__ import annotations

from dataclasses import asdict, replace
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app import audit, clock, tls
from app.account import (
    Profile,
    ProfileUpdate,
    SessionSummary,
    apply_profile,
    factor_infos,
    profile_of,
    session_summaries,
)
from app.auth.dependencies import (
    DB,
    client_ip,
    require,
    require_recent_confirmation,
    require_step_up,
)
from app.auth.mfa import (
    MfaFactor,
    RecoveryCode,
    confirmed_factors,
    mfa_required,
    unused_recovery_codes,
)
from app.auth.mfa_routes import FactorInfo
from app.auth.passwords import PasswordRejected
from app.auth.pwned import BreachCheckUnavailable
from app.auth.sessions import UserSession, end_sessions
from app.branding import LOGO_KEY, Branding, branding, save_branding
from app.colours import DEFAULT_ACCENT, DEFAULT_PRIMARY, SiteAccent, SitePrimary
from app.images import LOGO_SIZE, ImageRejected, avatar_url, clean_image, remove_image, store_image
from app.policy import (
    LIMITS,
    SecurityPolicy,
    admin_allowed_from,
    load_policy,
    login_allowed_from,
    normalize_networks,
    save_policy,
)
from app.roles import Capability, Role, grant_role, revoke_role, roles_of
from app.setup import set_company_name
from app.users import (
    NewPassword,
    User,
    create_user,
    find_user,
    set_password,
    temporary_password,
    vet_new_password,
)

router = APIRouter(prefix="/admin")

Admin = Annotated[UserSession, Depends(require(Capability.ADMINISTER))]


def _limit(name: str) -> Any:
    low, high = LIMITS[name]
    return Field(ge=low, le=high)


class SecuritySettings(BaseModel):
    """The security policy as people edit it, in the admin panel and the setup wizard."""

    min_password_length: int = _limit("min_password_length")
    breach_check_enabled: bool
    lockout_threshold: int = _limit("lockout_threshold")
    lockout_minutes: int = _limit("lockout_minutes")
    idle_timeout_minutes: int = _limit("idle_timeout_minutes")
    max_session_hours: int = _limit("max_session_hours")
    require_mfa_everyone: bool = True
    require_mfa_administrators: bool = True


class AdminSecurity(SecuritySettings):
    admin_allowlist_enabled: bool = False
    admin_allowlist: list[str] = Field(default=[], max_length=50)
    login_allowlist_enabled: bool = False
    login_allowlist: list[str] = Field(default=[], max_length=200)


class AdminSecurityView(AdminSecurity):
    your_address: str | None
    limits: dict[str, tuple[int, int]]


class UserSummary(Profile):
    id: int
    username: str
    avatar_url: str | None
    roles: list[Role]
    is_active: bool
    is_break_glass: bool
    locked: bool
    second_factors: int
    mfa_required: bool
    password_change_required: bool
    last_sign_in_at: datetime | None
    created_at: datetime


class UserDetail(UserSummary):
    password_expires_at: datetime | None
    factors: list[FactorInfo]
    recovery_codes_left: int
    sessions: list[SessionSummary]


class PasswordChoice(BaseModel):
    # Leave out to have Þing make a random one-time password.
    password: str | None = Field(default=None, min_length=1, max_length=1024)
    # A password the administrator chose is still replaced at first sign-in unless
    # they untick this; ASVS 6.4 expects initial passwords to be temporary.
    must_change_password: bool = True


class NewUser(ProfileUpdate, PasswordChoice):
    username: str = Field(min_length=1, max_length=150, pattern=r"^\S+$")
    display_name: str = Field(min_length=1, max_length=200)
    roles: list[Role] = []


class UserUpdate(ProfileUpdate):
    roles: list[Role] | None = None
    is_active: bool | None = None


class PasswordResult(BaseModel):
    user: UserDetail
    # Only when Þing made the password; one the administrator typed isn't echoed.
    temporary_password: str | None
    expires_at: datetime | None


class BrandingUpdate(BaseModel):
    site_name: str = Field(min_length=1, max_length=60)
    tagline: str = Field(default="", max_length=120)
    company_name: str = Field(min_length=1, max_length=200)
    primary_colour: SitePrimary = DEFAULT_PRIMARY
    accent_colour: SiteAccent = DEFAULT_ACCENT
    enforce_colours: bool = False


def _log(
    db: Session, request: Request, admin: UserSession, action: str, *,
    target: User | None = None, details: dict[str, object] | None = None,
) -> None:
    audit.append(
        db, action, actor_id=admin.user.id, actor_name=admin.user.username,
        target_type="user" if target else None, target_id=str(target.id) if target else None,
        ip=client_ip(request), details=details,
    )


def _summary_fields(db: Session, user: User, policy: SecurityPolicy) -> dict[str, Any]:
    locked_until = user.locked_until
    return {
        **profile_of(user),
        "id": user.id,
        "username": user.username,
        "avatar_url": avatar_url(db, user.id),
        "roles": sorted(roles_of(db, user.id)),
        "is_active": user.is_active,
        "is_break_glass": user.is_break_glass,
        "locked": locked_until is not None and locked_until > clock.utcnow(),
        "second_factors": len(confirmed_factors(db, user.id)),
        "mfa_required": mfa_required(db, user.id, policy),
        "password_change_required": user.must_change_password,
        "last_sign_in_at": user.last_sign_in_at,
        "created_at": user.created_at,
    }


def _detail(db: Session, user: User) -> UserDetail:
    return UserDetail(
        **_summary_fields(db, user, load_policy(db)),
        password_expires_at=user.password_expires_at,
        factors=factor_infos(db, user.id),
        recovery_codes_left=len(unused_recovery_codes(db, user.id)),
        sessions=session_summaries(db, user.id),
    )


def _target(db: Session, user_id: int) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That user doesn't exist.")
    return user


def _not_yourself(admin: UserSession, user: User, what: str) -> None:
    if user.id == admin.user_id:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"You can't {what} for yourself here. Use Your account."
        )


def _password_for(db: Session, choice: PasswordChoice, username: str) -> tuple[NewPassword, bool]:
    """The password to set, and whether Þing made it.

    Commits first: the checks hash and may call out to the network.
    """
    policy = load_policy(db)
    db.commit()
    if choice.password is None:
        return temporary_password(policy, username=username), True
    try:
        return vet_new_password(choice.password, policy, username=username), False
    except PasswordRejected as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except BreachCheckUnavailable as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Þing couldn't check that password against known data breaches. Try again, or "
            "let Þing make a random one.",
        ) from exc


def _password_log(generated: bool, temporary: bool) -> dict[str, object]:
    return {"password": "generated" if generated else "chosen by administrator",
            "must_change_password": temporary}


# Users


@router.get("/users")
def list_users(_: Admin, db: DB) -> list[UserSummary]:
    policy = load_policy(db)
    users = db.scalars(select(User).order_by(User.display_name, User.username))
    return [UserSummary(**_summary_fields(db, user, policy)) for user in users]


@router.post("/users")
def add_user(body: NewUser, request: Request, admin: Admin, db: DB) -> PasswordResult:
    if find_user(db, body.username) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "That username is taken.")
    password, generated = _password_for(db, body, body.username)
    temporary = generated or body.must_change_password
    user = create_user(db, body.username, body.display_name, password, temporary=temporary)
    apply_profile(user, body)
    for role in sorted(set(body.roles)):
        grant_role(db, user, role, actor=admin.user, ip=client_ip(request))
    _log(db, request, admin, "admin.user_created", target=user, details={
        "username": user.username, "roles": sorted(r.value for r in body.roles),
        **_password_log(generated, temporary),
    })
    db.commit()
    return PasswordResult(user=_detail(db, user),
                          temporary_password=password.value if generated else None,
                          expires_at=user.password_expires_at)


@router.get("/users/{user_id}")
def get_user(user_id: int, _: Admin, db: DB) -> UserDetail:
    return _detail(db, _target(db, user_id))


@router.patch("/users/{user_id}")
def update_user(user_id: int, body: UserUpdate, request: Request, admin: Admin, db: DB
                ) -> UserDetail:
    user = _target(db, user_id)
    current = roles_of(db, user.id)
    wanted = set(body.roles) if body.roles is not None else current
    deactivating = body.is_active is False and user.is_active
    losing_admin = Role.ADMINISTRATOR in current and Role.ADMINISTRATOR not in wanted

    if user.id == admin.user_id and deactivating:
        raise HTTPException(status.HTTP_409_CONFLICT, "You can't disable your own account.")
    if user.id == admin.user_id and losing_admin:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "You can't remove your own Administrator role."
        )
    # With these two rules an active Administrator always remains: whoever makes
    # the change is one, and can't step themselves down.
    if user.is_break_glass and (deactivating or losing_admin):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "The break-glass administrator always keeps the Administrator role and stays active.",
        )

    changes: dict[str, object] = {}
    if fields := apply_profile(user, body):
        changes["fields"] = fields
    if body.is_active is not None and body.is_active != user.is_active:
        changes["is_active"] = [user.is_active, body.is_active]
        user.is_active = body.is_active
        if not body.is_active:
            # Disabling locks them out at once: every session ends.
            changes["sessions_ended"] = end_sessions(db, user.id, "disabled")
    ip = client_ip(request)
    for role in sorted(wanted - current):
        grant_role(db, user, role, actor=admin.user, ip=ip)
    for role in sorted(current - wanted):
        revoke_role(db, user, role, actor=admin.user, ip=ip)
    if changes:
        _log(db, request, admin, "admin.user_updated", target=user, details=changes)
    db.commit()
    return _detail(db, user)


@router.post("/users/{user_id}/reset-password")
def reset_password(
    user_id: int, request: Request, admin: Admin, db: DB,
    body: Annotated[PasswordChoice | None, Body()] = None,
) -> PasswordResult:
    user = _target(db, user_id)
    _not_yourself(admin, user, "reset the password")
    choice = body or PasswordChoice()
    password, generated = _password_for(db, choice, user.username)
    temporary = generated or choice.must_change_password
    set_password(db, user, password, temporary=temporary)
    ended = end_sessions(db, user.id, "password_reset")
    _log(db, request, admin, "admin.password_reset", target=user,
         details={"sessions_ended": ended, **_password_log(generated, temporary)})
    db.commit()
    return PasswordResult(user=_detail(db, user),
                          temporary_password=password.value if generated else None,
                          expires_at=user.password_expires_at)


@router.post("/users/{user_id}/reset-mfa")
def reset_mfa(user_id: int, request: Request, admin: Admin, db: DB) -> UserDetail:
    """For a lost phone or key: the user sets up multifactor again at next sign-in."""
    user = _target(db, user_id)
    _not_yourself(admin, user, "reset multifactor")
    removed = len(confirmed_factors(db, user.id))
    db.execute(delete(MfaFactor).where(MfaFactor.user_id == user.id))
    db.execute(delete(RecoveryCode).where(RecoveryCode.user_id == user.id))
    ended = end_sessions(db, user.id, "mfa_reset")
    _log(db, request, admin, "admin.mfa_reset", target=user,
         details={"factors_removed": removed, "sessions_ended": ended})
    db.commit()
    return _detail(db, user)


@router.post("/users/{user_id}/unlock")
def unlock_user(user_id: int, request: Request, admin: Admin, db: DB) -> UserDetail:
    user = _target(db, user_id)
    user.locked_until = None
    user.failed_sign_ins = 0
    _log(db, request, admin, "admin.user_unlocked", target=user)
    db.commit()
    return _detail(db, user)


@router.post("/users/{user_id}/sign-out")
def sign_out_everywhere(user_id: int, request: Request, admin: Admin, db: DB) -> UserDetail:
    user = _target(db, user_id)
    _not_yourself(admin, user, "end every session")
    ended = end_sessions(db, user.id, "by_admin")
    _log(db, request, admin, "auth.sessions.ended", target=user,
         details={"count": ended, "by": "administrator"})
    db.commit()
    return _detail(db, user)


@router.post("/users/{user_id}/sessions/{session_id}/end")
def end_one_session(user_id: int, session_id: int, request: Request, admin: Admin, db: DB
                    ) -> UserDetail:
    user = _target(db, user_id)
    record = db.get(UserSession, session_id)
    if record is None or record.user_id != user.id or record.ended_reason is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That session doesn't exist.")
    if record.id == admin.id:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "That's the session you're using. Use Sign out instead.")
    record.ended_reason = "by_admin"
    _log(db, request, admin, "auth.sessions.ended", target=user,
         details={"count": 1, "by": "administrator", "session": session_id})
    db.commit()
    return _detail(db, user)


# Security


def _widened(was_on: bool, is_on: bool, old: tuple[str, ...], new: tuple[str, ...]) -> bool:
    """Addresses added to an allowlist that was on already. Switching one on, from
    everyone to these addresses, narrows who gets in."""
    return was_on and is_on and bool(set(new) - set(old))


def _weakens(old: SecurityPolicy, new: SecurityPolicy) -> bool:
    """Whether a change lowers security: these always need a fresh confirmation."""
    return any((
        new.min_password_length < old.min_password_length,
        old.breach_check_enabled and not new.breach_check_enabled,
        new.lockout_threshold > old.lockout_threshold,
        new.lockout_minutes < old.lockout_minutes,
        new.idle_timeout_minutes > old.idle_timeout_minutes,
        new.max_session_hours > old.max_session_hours,
        old.require_mfa_everyone and not new.require_mfa_everyone,
        old.require_mfa_administrators and not new.require_mfa_administrators,
        old.admin_allowlist_enabled and not new.admin_allowlist_enabled,
        old.login_allowlist_enabled and not new.login_allowlist_enabled,
        _widened(old.admin_allowlist_enabled, new.admin_allowlist_enabled,
                 old.admin_allowlist, new.admin_allowlist),
        _widened(old.login_allowlist_enabled, new.login_allowlist_enabled,
                 old.login_allowlist, new.login_allowlist),
    ))


def _changes_anything_but_new_passwords(old: SecurityPolicy, new: SecurityPolicy) -> bool:
    """Whether a change can sign people out or lock them out.

    Only stricter rules for new passwords (a longer minimum, the breach check on)
    touch no one's session.
    """
    password_rules = {"min_password_length", "breach_check_enabled"}
    before, after = asdict(old), asdict(new)
    return any(after[name] != before[name] for name in before if name not in password_rules)


def _security_view(db: Session, request: Request) -> AdminSecurityView:
    values = asdict(load_policy(db))
    values["admin_allowlist"] = list(values["admin_allowlist"])
    values["login_allowlist"] = list(values["login_allowlist"])
    return AdminSecurityView(**values, your_address=client_ip(request), limits=LIMITS)


@router.get("/security")
def get_security(request: Request, _: Admin, db: DB) -> AdminSecurityView:
    return _security_view(db, request)


@router.put("/security")
def update_security(body: AdminSecurity, request: Request, admin: Admin, db: DB
                    ) -> AdminSecurityView:
    try:
        admin_list = normalize_networks(body.admin_allowlist)
        login_list = normalize_networks(body.login_allowlist)
    except ValueError as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Each allowlist entry must be an address or a range, such as 10.0.0.0/24.",
        ) from exc
    for enabled, entries, name in ((body.admin_allowlist_enabled, admin_list, "admin panel"),
                                   (body.login_allowlist_enabled, login_list, "sign-in")):
        if enabled and not entries:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"Add at least one address to the {name} allowlist, or switch it off.",
            )
    old = load_policy(db)
    new = replace(
        old, **body.model_dump(exclude={"admin_allowlist", "login_allowlist"}),
        admin_allowlist=admin_list, login_allowlist=login_list,
    )
    ip = client_ip(request)
    if not admin_allowed_from(new, ip) or not login_allowed_from(new, ip):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Your own address ({ip}) isn't in the allowlist, so saving it would lock you out.",
        )
    # Lowering security needs the administrator to confirm it's them for this very
    # change, however recently they signed in; other changes that can sign people
    # out need a confirmation (or sign-in) in the last few minutes.
    if _weakens(old, new):
        require_step_up(admin)
    elif _changes_anything_but_new_passwords(old, new):
        require_recent_confirmation(admin)
    changes = {
        name: [before, after]
        for name, before in asdict(old).items()
        if (after := asdict(new)[name]) != before
    }
    if changes:
        save_policy(db, new)
        _log(db, request, admin, "admin.security_changed", details={"changes": changes})
    db.commit()
    if {"admin_allowlist", "admin_allowlist_enabled"} & changes.keys():
        tls.write_admin_allowlist(new.admin_allowlist_enabled, new.admin_allowlist)
    return _security_view(db, request)


# Branding


@router.put("/branding")
def update_branding(body: BrandingUpdate, request: Request, admin: Admin, db: DB) -> Branding:
    before = branding(db)
    save_branding(db, site_name=body.site_name, tagline=body.tagline,
                  primary_colour=body.primary_colour, accent_colour=body.accent_colour,
                  enforce_colours=body.enforce_colours)
    set_company_name(db, body.company_name)
    db.flush()
    after = branding(db)
    changes = {
        name: [getattr(before, name), getattr(after, name)]
        for name in ("site_name", "tagline", "company_name", "primary_colour",
                     "accent_colour", "enforce_colours")
        if getattr(before, name) != getattr(after, name)
    }
    if changes:
        _log(db, request, admin, "admin.branding_changed", details={"changes": changes})
    db.commit()
    return after


@router.put("/branding/logo")
def upload_logo(
    data: Annotated[bytes, Body(media_type="application/octet-stream")],
    request: Request, admin: Admin, db: DB,
) -> Branding:
    try:
        png = clean_image(data, max_size=LOGO_SIZE)
    except ImageRejected as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    store_image(db, LOGO_KEY, png)
    _log(db, request, admin, "admin.logo_changed")
    db.commit()
    return branding(db)


@router.delete("/branding/logo")
def remove_logo(request: Request, admin: Admin, db: DB) -> Branding:
    if remove_image(db, LOGO_KEY):
        _log(db, request, admin, "admin.logo_removed")
    db.commit()
    return branding(db)
