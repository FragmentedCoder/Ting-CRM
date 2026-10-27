"""Multifactor endpoints: enrol and verify authenticator apps and passkeys, use recovery codes."""

from __future__ import annotations

from datetime import datetime
from typing import Any, NoReturn

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import audit, clock
from app.auth import passkeys
from app.auth.dependencies import DB, AnySession, FullSession, client_ip, refuse
from app.auth.mfa import (
    Method,
    MfaFactor,
    begin_totp,
    confirm_totp,
    confirmed_factors,
    has_reusable_code,
    issue_recovery_codes,
    may_enrol,
    record_second_factor_failure,
    unused_recovery_codes,
    upgrade_session,
    use_recovery_code,
    verify_totp,
)
from app.auth.routes import SessionInfo, session_info, set_session_cookie
from app.auth.sessions import UserSession
from app.policy import load_policy

router = APIRouter(prefix="/auth/mfa")

WRONG_CODE = "That didn't work. Check the code and try again."


class CodeRequest(BaseModel):
    code: str = Field(min_length=1, max_length=64)


class TotpConfirmRequest(CodeRequest):
    label: str = Field(default="Authenticator app", min_length=1, max_length=100)


class TotpEnrolment(BaseModel):
    secret: str
    otpauth_uri: str


class PasskeyRegistration(BaseModel):
    credential: dict[str, Any]
    label: str = Field(default="Passkey", min_length=1, max_length=100)


class PasskeyAssertion(BaseModel):
    credential: dict[str, Any]


class SecondFactorResult(BaseModel):
    session: SessionInfo
    # Shown once, after the first factor is set up. Never retrievable again.
    recovery_codes: list[str] | None = None
    # The break-glass Administrator's one code, good every time.
    recovery_code_reusable: bool = False


class FactorInfo(BaseModel):
    id: int
    kind: str
    label: str
    created_at: datetime
    last_used_at: datetime | None


class FactorList(BaseModel):
    factors: list[FactorInfo]
    recovery_codes_left: int
    recovery_code_reusable: bool


def _actor(record: UserSession) -> dict[str, Any]:
    return {"actor_id": record.user.id, "actor_name": record.user.username}


def _require_enrolment_allowed(db: Session, record: UserSession) -> None:
    if record.user.must_change_password:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Choose a new password first.")
    if not may_enrol(db, record):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Finish signing in with multifactor authentication first."
        )


def _require_factors(db: Session, record: UserSession) -> None:
    locked_until = record.user.locked_until
    if locked_until is not None and locked_until > clock.utcnow():
        db.delete(record)
        db.commit()
        raise refuse(status.HTTP_401_UNAUTHORIZED, "Your account is locked for a few minutes "
                     "after too many wrong attempts.", "session_locked")
    if not confirmed_factors(db, record.user_id):
        raise HTTPException(status.HTTP_409_CONFLICT, "Set up multifactor authentication first.")


def _complete(
    db: Session,
    request: Request,
    response: Response,
    record: UserSession,
    method: Method,
    *,
    enrolled: MfaFactor | None = None,
    first_factor: bool = False,
) -> SecondFactorResult:
    """Both factors passed: rotate the session token, log it, set the new cookie."""
    actor, ip = _actor(record), client_ip(request)
    if enrolled is not None:
        audit.append(
            db, "auth.mfa.enrolled", **actor, ip=ip,
            details={"method": method, "label": enrolled.label},
        )
    codes = issue_recovery_codes(db, record.user_id) if first_factor else None
    if codes:
        audit.append(db, "auth.mfa.recovery_codes_issued", **actor, ip=ip,
                     details={"count": len(codes)})
    # Already past multifactor: this is a step-up, asked for by a sensitive change.
    stepping_up = record.mfa_verified_at is not None and enrolled is None
    token = upgrade_session(db, record)
    if stepping_up:
        record.step_up_at = clock.utcnow()
    audit.append(db, "auth.mfa.verified", **actor, ip=ip, details={"method": method})
    db.commit()
    set_session_cookie(response, token)
    return SecondFactorResult(session=session_info(db, record, token, request),
                              recovery_codes=codes,
                              recovery_code_reusable=has_reusable_code(db, record.user_id))


def _fail(db: Session, request: Request, record: UserSession, method: Method) -> NoReturn:
    actor, ip = _actor(record), client_ip(request)
    policy = load_policy(db)
    locked = record_second_factor_failure(db, record, policy)
    audit.append(db, "auth.mfa.failed", **actor, ip=ip, details={"method": method})
    if locked:
        audit.append(db, "auth.account.locked", **actor, ip=ip,
                     details={"minutes": policy.lockout_minutes})
    db.commit()
    if locked:
        raise refuse(status.HTTP_401_UNAUTHORIZED,
                     "Too many wrong attempts. Sign in again in a few minutes.", "session_locked")
    raise HTTPException(status.HTTP_400_BAD_REQUEST, WRONG_CODE)


# Authenticator apps


@router.post("/totp/enrol")
def enrol_totp(record: AnySession, db: DB) -> TotpEnrolment:
    _require_enrolment_allowed(db, record)
    secret, uri = begin_totp(db, record)
    db.commit()
    return TotpEnrolment(secret=secret, otpauth_uri=uri)


@router.post("/totp/confirm")
def confirm_totp_enrolment(
    body: TotpConfirmRequest, request: Request, response: Response, record: AnySession, db: DB
) -> SecondFactorResult:
    _require_enrolment_allowed(db, record)
    first_factor = not confirmed_factors(db, record.user_id)
    factor = confirm_totp(db, record, body.code, body.label)
    if factor is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, WRONG_CODE)
    return _complete(db, request, response, record, "totp", enrolled=factor,
                     first_factor=first_factor)


@router.post("/totp/verify")
def verify_totp_code(
    body: CodeRequest, request: Request, response: Response, record: AnySession, db: DB
) -> SecondFactorResult:
    _require_factors(db, record)
    if verify_totp(db, record, body.code) is None:
        _fail(db, request, record, "totp")
    return _complete(db, request, response, record, "totp")


# Recovery codes


@router.post("/recovery-code/verify")
def verify_recovery_code(
    body: CodeRequest, request: Request, response: Response, record: AnySession, db: DB
) -> SecondFactorResult:
    _require_factors(db, record)
    reusable = has_reusable_code(db, record.user_id)
    left = use_recovery_code(db, record.user_id, body.code)
    if left is None:
        _fail(db, request, record, "recovery_code")
    audit.append(db, "auth.recovery_code.used", **_actor(record), ip=client_ip(request),
                 details={"reusable": True} if reusable else {"left": left})
    return _complete(db, request, response, record, "recovery_code")


# Passkeys and hardware keys


@router.post("/passkey/registration-options")
def passkey_registration_options(record: AnySession, db: DB) -> dict[str, Any]:
    _require_enrolment_allowed(db, record)
    options = passkeys.registration_options(db, record)
    db.commit()
    return options


@router.post("/passkey/register")
def register_passkey(
    body: PasskeyRegistration, request: Request, response: Response, record: AnySession, db: DB
) -> SecondFactorResult:
    _require_enrolment_allowed(db, record)
    first_factor = not confirmed_factors(db, record.user_id)
    factor = passkeys.finish_registration(db, record, body.credential, body.label)
    if factor is None:
        db.commit()  # the challenge is spent either way
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "The passkey couldn't be registered. Try again."
        )
    return _complete(db, request, response, record, "webauthn", enrolled=factor,
                     first_factor=first_factor)


@router.post("/passkey/authentication-options")
def passkey_authentication_options(record: AnySession, db: DB) -> dict[str, Any]:
    _require_factors(db, record)
    if not any(f.kind == "webauthn" for f in confirmed_factors(db, record.user_id)):
        raise HTTPException(status.HTTP_409_CONFLICT, "No passkey is set up for this account.")
    options = passkeys.authentication_options(db, record)
    db.commit()
    return options


@router.post("/passkey/verify")
def verify_passkey(
    body: PasskeyAssertion, request: Request, response: Response, record: AnySession, db: DB
) -> SecondFactorResult:
    _require_factors(db, record)
    if passkeys.finish_authentication(db, record, body.credential) is None:
        _fail(db, request, record, "webauthn")
    return _complete(db, request, response, record, "webauthn")


@router.get("/factors")
def list_factors(record: FullSession, db: DB) -> FactorList:
    return FactorList(
        factors=[
            FactorInfo(id=f.id, kind=f.kind, label=f.label, created_at=f.created_at,
                       last_used_at=f.last_used_at)
            for f in confirmed_factors(db, record.user_id)
        ],
        recovery_codes_left=len(unused_recovery_codes(db, record.user_id)),
        recovery_code_reusable=has_reusable_code(db, record.user_id),
    )
