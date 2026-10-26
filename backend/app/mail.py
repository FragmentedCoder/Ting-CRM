"""Email: the mail server Þing sends through, and sending.

Administrators set it in the setup wizard or Admin -> Email: the server, how
the connection is secured (STARTTLS on 587 by default, or TLS from the start on
465; plain only for a relay on the same network), a user name and password,
and who mail comes from. The password is sealed with the config key (see
app/sealed_settings.py) and never sent back. Certificates are always checked.
Notices and, later, reminders send through here, and there's a test message that
shows the settings work.
"""

from __future__ import annotations

import smtplib
import socket
import ssl
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.policy import Setting
from app.sealed_settings import load_secrets

MAIL_SETTING = "mail/server"
SECRETS = "mail"
TIMEOUT = 15

Security = Literal["starttls", "tls", "none"]


class MailServer(BaseModel):
    host: str = Field(default="", max_length=253, pattern=r"^[A-Za-z0-9.-]*$")
    port: int = Field(default=587, ge=1, le=65535)
    security: Security = "starttls"
    username: str = Field(default="", max_length=254)
    from_address: str = Field(default="", max_length=254, pattern=r"^([^@\s]+@[^@\s]+)?$")
    from_name: str = Field(default="", max_length=100, pattern=r"^[^\r\n]*$")

    @property
    def configured(self) -> bool:
        return bool(self.host and self.from_address)


class MailError(Exception):
    """Sending failed, said plainly."""


def load_server(db: Session) -> MailServer:
    stored = db.scalar(select(Setting.value).where(Setting.key == MAIL_SETTING))
    return MailServer.model_validate_json(stored) if stored else MailServer()


def save_server(db: Session, server: MailServer) -> None:
    db.merge(Setting(key=MAIL_SETTING, value=server.model_dump_json()))


def _connect(server: MailServer) -> smtplib.SMTP:
    context = ssl.create_default_context()
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    if server.security == "tls":
        return smtplib.SMTP_SSL(server.host, server.port, timeout=TIMEOUT, context=context)
    smtp = smtplib.SMTP(server.host, server.port, timeout=TIMEOUT)
    if server.security == "starttls":
        smtp.starttls(context=context)
    return smtp


def send(server: MailServer, password: str, to: str, subject: str, body: str) -> None:
    """Send one plain-text message, or raise MailError saying why it couldn't be."""
    if not server.configured:
        raise MailError("Email isn't set up yet.")
    message = EmailMessage()
    message["From"] = formataddr((server.from_name, server.from_address))
    message["To"] = to
    message["Subject"] = subject
    message["Message-ID"] = make_msgid(domain=server.from_address.split("@")[-1])
    message.set_content(body)
    try:
        with _connect(server) as smtp:
            if server.username:
                smtp.login(server.username, password)
            smtp.send_message(message)
    except ssl.SSLCertVerificationError as exc:
        raise MailError("The mail server's certificate isn't trusted, or isn't for "
                        f"{server.host}.") from exc
    except smtplib.SMTPAuthenticationError as exc:
        raise MailError("The mail server refused the user name or password.") from exc
    except smtplib.SMTPNotSupportedError as exc:
        raise MailError("The mail server doesn't offer STARTTLS; try TLS on port 465.") from exc
    except smtplib.SMTPRecipientsRefused as exc:
        raise MailError(f"The mail server won't deliver to {to}.") from exc
    except smtplib.SMTPSenderRefused as exc:
        raise MailError(f"The mail server won't send from {server.from_address}.") from exc
    except TimeoutError as exc:
        raise MailError(f"The mail server at {server.host}:{server.port} didn't answer.") from exc
    except socket.gaierror as exc:
        raise MailError(f"Þing can't find a mail server called {server.host}: check the "
                        "name.") from exc
    except (OSError, smtplib.SMTPException) as exc:
        raise MailError(f"The mail server at {server.host}:{server.port} can't be reached "
                        f"or refused the message ({type(exc).__name__}).") from exc


def send_test(db: Session, to: str, company: str | None) -> None:
    """The test message, with what's saved."""
    server = load_server(db)
    password = str(load_secrets(db, SECRETS).get("password", ""))
    db.commit()  # the network follows: hold no lock meanwhile
    send(server, password, to, f"Test from {company or 'Þing'}",
         "This is a test message from Þing. Email is set up: notices and reminders can be "
         "sent from here.\n")
