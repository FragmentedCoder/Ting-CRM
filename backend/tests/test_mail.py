import smtplib
import socket
import ssl

import pytest
from sqlalchemy import select

from app import mail
from app.audit import AuditEntry
from app.mail import MailError, MailServer
from app.roles import Role, grant_role
from app.settings import settings
from tests.conftest import PASSWORD

EMAIL = "/api/admin/email"
SERVER = {"host": "smtp.nordlys.example", "port": 587, "security": "starttls",
          "username": "ting", "from_address": "ting@nordlys.example",
          "from_name": "Nordlys IT"}


class FakeSMTP:
    """Stands in for smtplib's SMTP and SMTP_SSL; records what happens."""

    sent: list[dict] = []
    fail: Exception | None = None

    def __init__(self, host, port, timeout=None, context=None):
        self.record = {"host": host, "port": port, "tls_from_start": context is not None,
                       "starttls": False, "login": None}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self, context=None):
        assert context is not None and context.verify_mode == ssl.CERT_REQUIRED
        assert context.minimum_version == ssl.TLSVersion.TLSv1_2
        self.record["starttls"] = True

    def login(self, username, password):
        self.record["login"] = (username, password)

    def send_message(self, message):
        if FakeSMTP.fail is not None:
            raise FakeSMTP.fail
        self.record["message"] = message
        FakeSMTP.sent.append(self.record)


@pytest.fixture
def smtp(monkeypatch, data_dir):
    monkeypatch.setattr(settings, "data_dir", str(data_dir))
    FakeSMTP.sent, FakeSMTP.fail = [], None
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSMTP)
    return FakeSMTP


def test_a_message_goes_out_over_starttls_signed_in(smtp) -> None:
    mail.send(MailServer(**SERVER), "pw", "ingrid@nordlys.example", "Hello", "Body\n")
    [sent] = smtp.sent
    assert (sent["host"], sent["port"], sent["starttls"], sent["tls_from_start"]) == (
        "smtp.nordlys.example", 587, True, False)
    assert sent["login"] == ("ting", "pw")
    message = sent["message"]
    assert message["From"] == "Nordlys IT <ting@nordlys.example>"
    assert message["To"] == "ingrid@nordlys.example" and message["Subject"] == "Hello"
    assert message["Message-ID"].endswith("@nordlys.example>")


def test_tls_from_the_start_and_a_relay_without_login(smtp) -> None:
    mail.send(MailServer(**SERVER | {"security": "tls", "port": 465}), "", "a@b.example",
              "s", "b")
    mail.send(MailServer(**SERVER | {"security": "none", "port": 25, "username": ""}), "",
              "a@b.example", "s", "b")
    first, second = smtp.sent
    assert first["tls_from_start"] and not first["starttls"]
    assert not second["starttls"] and second["login"] is None


@pytest.mark.parametrize(("error", "said"), [
    (smtplib.SMTPAuthenticationError(535, b"no"), "refused the user name or password"),
    (ssl.SSLCertVerificationError("bad"), "certificate isn't trusted"),
    (smtplib.SMTPRecipientsRefused({}), "won't deliver to a@b.example"),
    (TimeoutError(), "didn't answer"),
    (socket.gaierror(-2, "Name or service not known"),
     "can't find a mail server called smtp.nordlys.example"),
    (ConnectionRefusedError(), "can't be reached"),
])
def test_failures_are_said_plainly(smtp, error, said) -> None:
    smtp.fail = error
    with pytest.raises(MailError, match=said):
        mail.send(MailServer(**SERVER), "pw", "a@b.example", "s", "b")


def test_nothing_is_sent_before_email_is_set_up(smtp) -> None:
    with pytest.raises(MailError, match="isn't set up"):
        mail.send(MailServer(), "", "a@b.example", "s", "b")


def test_header_injection_is_refused() -> None:
    with pytest.raises(ValueError):
        MailServer(**SERVER | {"from_name": "Nordlys\r\nBcc: everyone@example.com"})
    with pytest.raises(ValueError):
        MailServer(**SERVER | {"host": "smtp.example\r\nRCPT"})


# The admin panel


def test_changing_the_mail_server_needs_a_fresh_confirmation(client, admin, smtp,
                                                            session) -> None:
    _, headers = admin
    assert client.get(EMAIL, headers=headers).json()["password_set"] is False
    refused = client.put(EMAIL, headers=headers, json=SERVER | {"password": "mail-secret"})
    assert refused.headers["X-Ting-Reason"] == "step_up_required"
    assert "sends email" in refused.json()["detail"]
    client.post("/api/auth/confirm-password", headers=headers, json={"password": PASSWORD})
    saved = client.put(EMAIL, headers=headers, json=SERVER | {"password": "mail-secret"})
    assert saved.status_code == 200 and saved.json()["password_set"]
    assert "mail-secret" not in saved.text
    # Who mail comes from changes without asking again; the password is kept.
    renamed = client.put(EMAIL, headers=headers, json=SERVER | {"from_name": "Þing"})
    assert renamed.status_code == 200 and renamed.json()["server"]["from_name"] == "Þing"
    assert client.get(EMAIL, headers=headers).json()["password_set"]
    logged = session.scalars(select(AuditEntry.details).where(
        AuditEntry.action == "mail.settings_changed")).all()
    assert len(logged) == 2 and all("mail-secret" not in d for d in logged)


def test_the_test_message_uses_what_is_saved(client, admin, smtp, session) -> None:
    _, headers = admin
    client.post("/api/auth/confirm-password", headers=headers, json={"password": PASSWORD})
    client.put(EMAIL, headers=headers, json=SERVER | {"password": "mail-secret"})
    sent = client.post(f"{EMAIL}/test", headers=headers, json={"to": "ingrid@nordlys.example"})
    assert sent.status_code == 204
    assert smtp.sent[0]["login"] == ("ting", "mail-secret")
    smtp.fail = smtplib.SMTPAuthenticationError(535, b"no")
    failed = client.post(f"{EMAIL}/test", headers=headers, json={"to": "ingrid@nordlys.example"})
    assert failed.status_code == 400 and "refused the user name" in failed.json()["detail"]
    actions = session.scalars(select(AuditEntry.action).where(
        AuditEntry.action.like("mail.test%")).order_by(AuditEntry.seq)).all()
    assert actions == ["mail.test_sent", "mail.test_failed"]


def test_a_server_without_a_from_address_is_refused(client, admin, smtp) -> None:
    _, headers = admin
    refused = client.put(EMAIL, headers=headers, json=SERVER | {"from_address": ""})
    assert refused.status_code == 400 and "comes from" in refused.json()["detail"]


def test_only_administrators_reach_email(client, make_user, session, full_session) -> None:
    technician = make_user("tor")
    grant_role(session, technician, Role.TECHNICIAN, actor=None, ip=None)
    session.commit()
    assert client.get(EMAIL, headers=full_session(technician)).status_code == 403
