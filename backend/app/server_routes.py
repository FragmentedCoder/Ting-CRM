"""Email and the certificate, in the admin panel (Administrators only).

Changing where mail goes out, or which certificate Þing serves, asks the
person to confirm it's them. The setup wizard saves the same settings through
apply_mail and apply_tls, without that question: the one setting up has just
signed in with multifactor. Passwords and keys are written, never read back.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import audit, mail, tls
from app.admin import Admin
from app.auth.dependencies import DB, client_ip, require_step_up
from app.auth.sessions import UserSession
from app.mail import MailError, MailServer
from app.sealed_settings import load_secrets, save_secrets
from app.setup import company_name
from app.tls import Certificate, TlsError, TlsSettings

router = APIRouter(prefix="/admin")

EMAIL = r"^[^@\s]+@[^@\s]+$"


class MailIn(MailServer):
    # Left out (None) keeps the saved one.
    password: str | None = Field(default=None, max_length=500)


class MailStatus(BaseModel):
    server: MailServer
    password_set: bool


class MailTest(BaseModel):
    to: str = Field(max_length=254, pattern=EMAIL)


class TlsIn(TlsSettings):
    certificate_pem: str | None = Field(default=None, max_length=100_000)
    key_pem: str | None = Field(default=None, max_length=20_000)
    # Left out (None) keeps the saved one.
    cloudflare_token: str | None = Field(default=None, pattern=tls.CLOUDFLARE_TOKEN)
    rfc2136_key: str | None = Field(default=None, pattern=tls.TSIG_KEY)


class TlsStatus(BaseModel):
    settings: TlsSettings
    host: str
    served: Certificate | None
    # Where computers get the root certificate to trust, with Caddy's own authority.
    root_url: str | None
    cloudflare_token_set: bool
    rfc2136_key_set: bool


def _log(db: Session, request: Request, who: UserSession, action: str,
         details: dict[str, Any]) -> None:
    audit.append(db, action, actor_id=who.user.id, actor_name=who.user.username,
                 ip=client_ip(request), details=details)


def mail_status(db: Session) -> MailStatus:
    return MailStatus(server=mail.load_server(db),
                      password_set=bool(load_secrets(db, mail.SECRETS).get("password")))


def apply_mail(db: Session, request: Request, who: UserSession, body: MailIn,
               confirm: bool) -> MailStatus:
    """Save the mail server; with confirm, a new server or password asks for step-up."""
    server = MailServer.model_validate(body.model_dump(exclude={"password"}))
    if not server.configured:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Name the mail server and the address mail comes from.")
    before = mail.load_server(db)
    if confirm and (server.host != before.host or server.username != before.username
                    or body.password is not None):
        require_step_up(who, "Confirm it's you to change how Þing sends email.")
    secrets = load_secrets(db, mail.SECRETS)
    if body.password is not None:
        secrets["password"] = body.password
    mail.save_server(db, server)
    save_secrets(db, mail.SECRETS, secrets)
    _log(db, request, who, "mail.settings_changed", {
        "host": server.host, "port": server.port, "security": server.security})
    db.commit()
    return mail_status(db)


def send_test(db: Session, request: Request, who: UserSession, to: str) -> None:
    company = company_name(db)
    try:
        mail.send_test(db, to, company)
    except MailError as exc:
        _log(db, request, who, "mail.test_failed", {"to": to, "error": str(exc)})
        db.commit()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    _log(db, request, who, "mail.test_sent", {"to": to})
    db.commit()


def tls_status(db: Session) -> TlsStatus:
    saved = tls.load_tls(db)
    secrets = load_secrets(db, tls.SECRETS)
    db.commit()  # asking Caddy follows: hold no lock meanwhile
    return TlsStatus(settings=saved, host=tls.host(), served=tls.served_certificate(),
                     root_url="/ting-root.crt" if saved.mode == "internal" else None,
                     cloudflare_token_set=bool(secrets.get("cloudflare_token")),
                     rfc2136_key_set=bool(secrets.get("rfc2136_key")))


def apply_tls(db: Session, request: Request, who: UserSession, body: TlsIn,
              confirm: bool) -> TlsStatus:
    """Check and save the TLS settings, and hand them to Caddy."""
    saved = TlsSettings.model_validate(body.model_dump(include=set(TlsSettings.model_fields)))
    saved.certificate = None
    chain = key = None
    secrets = load_secrets(db, tls.SECRETS)
    if body.cloudflare_token is not None:
        secrets["cloudflare_token"] = body.cloudflare_token
    if body.rfc2136_key is not None:
        secrets["rfc2136_key"] = body.rfc2136_key
    if missing := saved.dns_missing(secrets):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, missing)
    if body.mode == "acme" and not tls.public_name(tls.host()):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, (
            f"Let's Encrypt only issues certificates for addresses on the internet, and "
            f"{tls.host()} isn't one. Use Caddy's own authority or your own certificate."))
    if body.mode == "own":
        if not body.certificate_pem or not body.key_pem:
            current = tls.load_tls(db)
            if current.mode != "own" or current.certificate is None:
                raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                    "Upload the certificate and its key.")
            saved.certificate = current.certificate  # keep the uploaded one
        else:
            try:
                saved.certificate = tls.check_certificate(body.certificate_pem, body.key_pem,
                                                          tls.host())
            except TlsError as exc:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
            chain, key = body.certificate_pem, body.key_pem
    if confirm:
        require_step_up(who, "Confirm it's you to change Þing's certificate.")
    tls.save_tls(db, saved)
    save_secrets(db, tls.SECRETS, secrets)
    _log(db, request, who, "tls.changed", {
        "mode": saved.mode,
        **({"challenge": saved.challenge} if saved.mode == "acme" else {}),
        **({"dns": saved.dns_provider} if saved.mode == "acme" and saved.challenge == "dns"
           else {}),
        **({"certificate": saved.certificate.subject,
            "not_after": saved.certificate.not_after.isoformat()} if saved.certificate else {}),
    })
    db.commit()
    tls.write_for_caddy(saved, chain, key, secrets)
    return tls_status(db)


@router.get("/email")
def get_mail(_: Admin, db: DB) -> MailStatus:
    return mail_status(db)


@router.put("/email")
def change_mail(body: MailIn, request: Request, admin: Admin, db: DB) -> MailStatus:
    return apply_mail(db, request, admin, body, confirm=True)


@router.post("/email/test", status_code=status.HTTP_204_NO_CONTENT)
def test_mail(body: MailTest, request: Request, admin: Admin, db: DB) -> None:
    send_test(db, request, admin, body.to)


@router.get("/tls")
def get_tls(_: Admin, db: DB) -> TlsStatus:
    return tls_status(db)


@router.put("/tls")
def change_tls(body: TlsIn, request: Request, admin: Admin, db: DB) -> TlsStatus:
    return apply_tls(db, request, admin, body, confirm=True)
