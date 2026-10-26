"""Passkeys and hardware security keys (WebAuthn / FIDO2), used for multifactor sign-in."""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from urllib.parse import urlsplit

import webauthn
from sqlalchemy import select
from sqlalchemy.orm import Session
from webauthn.helpers import base64url_to_bytes, generate_user_handle, options_to_json_dict
from webauthn.helpers.exceptions import WebAuthnException
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    AuthenticatorTransport,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from app import clock
from app.auth.mfa import MfaFactor, confirmed_factors
from app.auth.sessions import UserSession
from app.settings import settings

RP_NAME = "Þing"
CHALLENGE_LIFETIME = timedelta(minutes=5)
_KNOWN_TRANSPORTS = {t.value for t in AuthenticatorTransport}


def relying_party() -> tuple[str, str]:
    """(RP ID, origin) from TING_ADDRESS; passkeys only work at that exact address."""
    parts = urlsplit(settings.address)
    if not parts.hostname:
        raise RuntimeError(f"TING_ADDRESS has no host name: {settings.address!r}")
    return parts.hostname, f"{parts.scheme}://{parts.netloc}"


def _set_challenge(record: UserSession, purpose: str, challenge: bytes) -> None:
    record.challenge = challenge
    record.challenge_purpose = purpose
    record.challenge_expires_at = clock.utcnow() + CHALLENGE_LIFETIME


def _take_challenge(record: UserSession, purpose: str) -> bytes | None:
    """The pending challenge, if it is for this purpose and fresh. Usable once either way."""
    fresh = (
        record.challenge_purpose == purpose
        and record.challenge_expires_at is not None
        and record.challenge_expires_at > clock.utcnow()
    )
    challenge = record.challenge if fresh else None
    record.challenge = None
    record.challenge_purpose = None
    record.challenge_expires_at = None
    return challenge


def _descriptor(factor: MfaFactor) -> PublicKeyCredentialDescriptor:
    assert factor.credential_id is not None
    transports = [
        AuthenticatorTransport(t)
        for t in (factor.transports or "").split(",")
        if t in _KNOWN_TRANSPORTS
    ]
    return PublicKeyCredentialDescriptor(id=factor.credential_id, transports=transports or None)


def _passkeys(db: Session, user_id: int) -> list[MfaFactor]:
    return [f for f in confirmed_factors(db, user_id) if f.kind == "webauthn"]


def registration_options(db: Session, record: UserSession) -> dict[str, Any]:
    user = record.user
    if user.webauthn_handle is None:
        user.webauthn_handle = generate_user_handle()
    rp_id, _ = relying_party()
    options = webauthn.generate_registration_options(
        rp_id=rp_id,
        rp_name=RP_NAME,
        user_id=user.webauthn_handle,
        user_name=user.username,
        user_display_name=user.display_name,
        exclude_credentials=[_descriptor(f) for f in _passkeys(db, user.id)],
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.PREFERRED,
            user_verification=UserVerificationRequirement.PREFERRED,
        ),
    )
    _set_challenge(record, "register", options.challenge)
    return options_to_json_dict(options)


def finish_registration(
    db: Session, record: UserSession, credential: dict[str, Any], label: str
) -> MfaFactor | None:
    challenge = _take_challenge(record, "register")
    if challenge is None:
        return None
    rp_id, origin = relying_party()
    try:
        verified = webauthn.verify_registration_response(
            credential=credential,
            expected_challenge=challenge,
            expected_rp_id=rp_id,
            expected_origin=origin,
        )
    except WebAuthnException:
        return None
    response = credential.get("response")
    transports = response.get("transports") if isinstance(response, dict) else None
    now = clock.utcnow()
    factor = MfaFactor(
        user_id=record.user_id,
        kind="webauthn",
        label=label,
        created_at=now,
        confirmed_at=now,
        last_used_at=now,
        credential_id=verified.credential_id,
        public_key=verified.credential_public_key,
        sign_count=verified.sign_count,
        transports=",".join(t for t in transports or [] if t in _KNOWN_TRANSPORTS) or None,
    )
    db.add(factor)
    return factor


def authentication_options(db: Session, record: UserSession) -> dict[str, Any]:
    rp_id, _ = relying_party()
    options = webauthn.generate_authentication_options(
        rp_id=rp_id,
        allow_credentials=[_descriptor(f) for f in _passkeys(db, record.user_id)],
        user_verification=UserVerificationRequirement.PREFERRED,
    )
    _set_challenge(record, "authenticate", options.challenge)
    return options_to_json_dict(options)


def finish_authentication(
    db: Session, record: UserSession, credential: dict[str, Any]
) -> MfaFactor | None:
    challenge = _take_challenge(record, "authenticate")
    if challenge is None:
        return None
    try:
        credential_id = base64url_to_bytes(str(credential["rawId"]))
    except (KeyError, ValueError):
        return None
    factor = db.scalar(
        select(MfaFactor).where(
            MfaFactor.user_id == record.user_id,
            MfaFactor.kind == "webauthn",
            MfaFactor.credential_id == credential_id,
            MfaFactor.confirmed_at.is_not(None),
        )
    )
    if factor is None or factor.public_key is None:
        return None
    rp_id, origin = relying_party()
    try:
        verified = webauthn.verify_authentication_response(
            credential=credential,
            expected_challenge=challenge,
            expected_rp_id=rp_id,
            expected_origin=origin,
            credential_public_key=factor.public_key,
            credential_current_sign_count=factor.sign_count or 0,
        )
    except WebAuthnException:
        return None
    factor.sign_count = verified.new_sign_count
    factor.last_used_at = clock.utcnow()
    return factor
