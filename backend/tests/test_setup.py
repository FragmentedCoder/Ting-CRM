import httpx
import pyotp
import pytest
from sqlalchemy import select

from app import db as db_module
from app import setup as setup_state
from app import tls
from app.audit import AuditEntry, verify
from app.auth import pwned
from app.crypto.key_files import load_or_create_backup_key
from app.crypto.keys import from_kit_text
from app.policy import Setting, load_policy
from app.roles import Role, grant_role
from app.settings import settings
from app.setup import new_setup_token
from tests.conftest import PASSWORD

ADMIN = {"username": "admin", "display_name": "Ingrid Admin", "password": PASSWORD}


@pytest.fixture
def server(monkeypatch, data_dir, master_key_path, tmp_path):
    """The app reads its keys from settings; point them at this test's files."""
    monkeypatch.setattr(settings, "data_dir", str(data_dir))
    monkeypatch.setattr(settings, "master_key_path", str(master_key_path))
    monkeypatch.setattr(settings, "address", "https://ting.example.internal")
    monkeypatch.setattr(settings, "tls_dir", str(tmp_path / "tls"))
    monkeypatch.setattr(tls, "served_certificate", lambda: None)


@pytest.fixture
def token(session):
    value = new_setup_token(session)
    session.commit()
    return value


def h(token, csrf=None):
    headers = {"X-Setup-Token": token}
    if csrf:
        headers["X-CSRF-Token"] = csrf
    return headers


def actions(session):
    found = list(session.scalars(select(AuditEntry.action).order_by(AuditEntry.seq)))
    session.commit()
    return found


def create_admin(client, token, **overrides):
    return client.post("/api/setup/administrator", json=ADMIN | overrides, headers=h(token))


def enrol_app(client, csrf):
    secret = client.post("/api/auth/mfa/totp/enrol", headers={"X-CSRF-Token": csrf}).json()
    result = client.post(
        "/api/auth/mfa/totp/confirm",
        json={"code": pyotp.TOTP(secret["secret"]).now()},
        headers={"X-CSRF-Token": csrf},
    )
    return result.json()["session"]["csrf_token"]


def test_a_fresh_install_needs_setup(client) -> None:
    assert client.get("/api/setup/status").json() == {"needed": True}


def test_every_step_needs_the_setup_token(client, token, session) -> None:
    for wrong in ({}, h("AAAA-AAAA-AAAA-AAAA-AAAA-AAAA")):
        response = client.post("/api/setup/company", json={"name": "Nordlys IT ApS"}, headers=wrong)
        assert response.status_code == 401
    assert actions(session) == ["setup.token_rejected"] * 2
    ok = client.post("/api/setup/company", json={"name": "Nordlys IT ApS"},
                     headers=h(token.lower().replace("-", " ")))
    assert ok.status_code == 200


def test_guessing_the_token_is_throttled(client, token) -> None:
    for _ in range(10):
        client.post("/api/setup/progress", headers=h("BBBB-BBBB-BBBB-BBBB-BBBB-BBBB"))
    assert client.post("/api/setup/progress", headers=h(token)).status_code == 429


def test_the_token_command_prints_a_token_and_stores_only_its_hash(
    engine, session, capsys, monkeypatch, server
) -> None:
    monkeypatch.setattr(db_module, "get_engine", lambda: engine)
    setup_state.main()
    printed = capsys.readouterr().out
    token = printed.split("Setup token: ")[1].split()[0]

    assert "https://ting.example.internal/setup" in printed
    assert setup_state.setup_token_valid(session, token)
    stored = session.get(Setting, setup_state.SETUP_KEY).value
    session.commit()
    assert token not in stored and token.replace("-", "") not in stored


SECURITY = {
    "min_password_length": 14, "breach_check_enabled": True, "lockout_threshold": 5,
    "lockout_minutes": 30, "idle_timeout_minutes": 20, "max_session_hours": 10,
    "require_mfa_everyone": False, "require_mfa_administrators": True,
}


def test_the_whole_wizard(client, token, session, server, no_breach_found, master_key_path,
                          data_dir) -> None:
    progress = client.post("/api/setup/company", json={"name": "Nordlys IT ApS"},
                           headers=h(token)).json()
    assert progress["address"] == "https://ting.example.internal"
    assert progress["security"]["min_password_length"] == 12  # the defaults, to review
    assert not progress["security_reviewed"]
    reviewed = client.post("/api/setup/security", json=SECURITY, headers=h(token)).json()
    assert reviewed["security_reviewed"] and reviewed["security"] == SECURITY

    created = create_admin(client, token)
    assert created.status_code == 200
    info = created.json()
    assert info["user"]["roles"] == ["administrator"]
    assert info["second_factor"] == "enrol"

    # The keys are shown only once the administrator has a second factor.
    early = client.post("/api/setup/recovery-kit", headers=h(token, info["csrf_token"]))
    assert early.status_code == 403
    csrf = enrol_app(client, info["csrf_token"])

    kit = client.post("/api/setup/recovery-kit", headers=h(token, csrf)).json()
    assert from_kit_text(kit["master_key"]) == master_key_path.read_bytes()
    assert from_kit_text(kit["backup_key"]) == load_or_create_backup_key(data_dir, master_key_path)
    assert (kit["company_name"], kit["address"]) == (
        "Nordlys IT ApS", "https://ting.example.internal"
    )

    early = client.post("/api/setup/backups", json={"targets": [{"kind": "local"}]},
                        headers=h(token, csrf))
    assert early.json()["detail"] == "Save the recovery kit first."
    saved = client.post("/api/setup/kit-saved", headers=h(token, csrf)).json()
    assert saved["kit_saved"] and saved["steps_done"] == []

    # Then backups, email and the certificate: no step-up asked, each can wait.
    backups = client.post("/api/setup/backups", json={"targets": [{"kind": "local"}], "hour": 3},
                          headers=h(token, csrf))
    assert backups.json()["hour"] == 3 and backups.json()["targets"][0]["words"] == "this server"
    unfinished = client.post("/api/setup/complete", headers=h(token, csrf))
    assert unfinished.json()["detail"] == "Set up email, or leave it for later, first."
    mail = client.post("/api/setup/email", headers=h(token, csrf), json={
        "host": "smtp.nordlys.example", "from_address": "ting@nordlys.example",
        "username": "ting", "password": "mail-secret"})
    assert mail.json()["password_set"] and "mail-secret" not in mail.text
    later = client.post("/api/setup/later/tls", headers=h(token, csrf)).json()
    assert later["steps_done"] == ["backups", "email", "tls"]

    done = client.post("/api/setup/complete", headers=h(token, csrf))
    assert done.json() == {"needed": False}
    assert client.get("/api/setup/status").json() == {"needed": False}

    # Closed for good: the token, the kit and every step.
    assert client.post("/api/setup/recovery-kit", headers=h(token, csrf)).status_code == 410
    assert create_admin(client, token, username="second").status_code == 410
    assert actions(session)[-1] == "setup.completed"
    for logged in ("setup.recovery_kit_shown", "setup.recovery_kit_saved",
                   "backup.settings_changed", "mail.settings_changed",
                   "setup.step_left_for_later"):
        assert logged in actions(session), logged
    assert verify(session).ok


def test_only_one_break_glass_administrator(client, token, server, no_breach_found) -> None:
    create_admin(client, token)
    again = create_admin(client, token, username="another")
    assert again.status_code == 409
    assert "Sign in as admin" in again.json()["detail"]


def test_a_breached_password_is_refused(client, token, server, monkeypatch) -> None:
    # The breach service's protocol is tested in test_pwned.py; here only the answer matters.
    monkeypatch.setattr(pwned, "times_breached", lambda password: 12)
    response = create_admin(client, token)
    assert response.status_code == 400
    assert "data breach" in response.json()["detail"]


def test_an_offline_server_can_turn_the_breach_check_off_explicitly(
    client, token, session, server, monkeypatch
) -> None:
    def offline(request):
        raise httpx.ConnectError("no route to host")

    monkeypatch.setattr(
        pwned, "_client", lambda: httpx.Client(transport=httpx.MockTransport(offline))
    )
    assert create_admin(client, token).status_code == 503
    assert load_policy(session).breach_check_enabled
    session.commit()  # end the read: an open transaction holds the write lock

    assert create_admin(client, token, skip_breach_check=True).status_code == 200
    assert not load_policy(session).breach_check_enabled
    session.commit()
    assert "setup.breach_check_turned_off" in actions(session)


def test_the_kit_is_only_for_the_setup_administrator(
    client, token, session, make_user, full_session, server
) -> None:
    other = make_user("another-admin", display_name="Another")
    grant_role(session, other, Role.ADMINISTRATOR, actor=None, ip=None)
    session.commit()
    headers = full_session(other) | {"X-Setup-Token": token}
    assert client.post("/api/setup/recovery-kit", headers=headers).status_code == 403


def test_the_security_step_checks_its_limits(client, token, session) -> None:
    for field, value in (("min_password_length", 6), ("lockout_threshold", 500)):
        response = client.post("/api/setup/security", json=SECURITY | {field: value},
                               headers=h(token))
        assert response.status_code == 422, field
    assert load_policy(session).min_password_length == 12
    session.commit()


def test_setup_cannot_finish_before_security_is_reviewed(
    client, token, server, no_breach_found
) -> None:
    client.post("/api/setup/company", json={"name": "Nordlys IT ApS"}, headers=h(token))
    csrf = enrol_app(client, create_admin(client, token).json()["csrf_token"])
    client.post("/api/setup/recovery-kit", headers=h(token, csrf))
    response = client.post("/api/setup/complete", headers=h(token, csrf))
    assert response.json()["detail"] == "Review the security settings first."


def test_setup_cannot_finish_before_the_kit_is_shown(
    client, token, server, no_breach_found
) -> None:
    client.post("/api/setup/company", json={"name": "Nordlys IT ApS"}, headers=h(token))
    client.post("/api/setup/security", json=SECURITY, headers=h(token))
    csrf = enrol_app(client, create_admin(client, token).json()["csrf_token"])
    assert client.post("/api/setup/kit-saved", headers=h(token, csrf)).status_code == 409
    response = client.post("/api/setup/complete", headers=h(token, csrf))
    assert response.json()["detail"] == "Save the recovery kit before finishing setup."
    client.post("/api/setup/recovery-kit", headers=h(token, csrf))
    response = client.post("/api/setup/complete", headers=h(token, csrf))
    assert response.json()["detail"] == "Save the recovery kit before finishing setup."


def test_break_glass_sign_ins_are_flagged(client, token, session, server, no_breach_found) -> None:
    create_admin(client, token)
    client.cookies.clear()
    client.post("/api/auth/sign-in", json={"username": "admin", "password": PASSWORD})
    flagged = session.scalars(
        select(AuditEntry.details).where(AuditEntry.action == "auth.sign_in.succeeded")
    ).all()
    session.commit()
    assert all('"break_glass":true' in d for d in flagged) and len(flagged) == 2
