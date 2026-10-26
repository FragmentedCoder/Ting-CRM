import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from sqlalchemy import select

from app import tls
from app.audit import AuditEntry
from app.settings import settings
from app.tls import TlsError, TlsSettings
from tests.conftest import PASSWORD

TLS = "/api/admin/tls"
NOW = datetime(2026, 10, 25, 12, 0, tzinfo=UTC)


def _key_pem(key) -> str:
    return key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                             serialization.NoEncryption()).decode()


def make_certificate(*names: str, days: int = 90, starts: int = -1, key=None,
                     common: bool = True) -> tuple[str, str]:
    """A self-signed certificate for the names, and its key, as PEM."""
    key = key or ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, names[0] if names else "x")]
                        if common else [])
    builder = (
        x509.CertificateBuilder().subject_name(subject).issuer_name(subject)
        .public_key(key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(NOW + timedelta(days=starts))
        .not_valid_after(NOW + timedelta(days=days))
    )
    if names:
        builder = builder.add_extension(
            x509.SubjectAlternativeName([x509.DNSName(n) for n in names]), critical=False)
    cert = builder.sign(key, hashes.SHA256())
    return cert.public_bytes(serialization.Encoding.PEM).decode(), _key_pem(key)


@pytest.fixture
def tls_dir(monkeypatch, tmp_path, data_dir):
    folder = tmp_path / "tls"
    monkeypatch.setattr(settings, "tls_dir", str(folder))
    monkeypatch.setattr(settings, "data_dir", str(data_dir))
    monkeypatch.setattr(settings, "address", "https://ting.nordlys.example.com")
    monkeypatch.setattr(tls, "served_certificate", lambda: None)
    return folder


def test_a_certificate_without_a_common_name_is_named_by_its_first_name() -> None:
    chain, key = make_certificate("ting.nordlys.example.com", common=False)
    described = tls.check_certificate(chain, key, "ting.nordlys.example.com", NOW)
    assert described.subject == "ting.nordlys.example.com"


def test_a_matching_certificate_for_the_address_is_described() -> None:
    chain, key = make_certificate("ting.nordlys.example.com", "alt.nordlys.example")
    described = tls.check_certificate(chain, key, "ting.nordlys.example.com", NOW)
    assert described.subject == "ting.nordlys.example.com"
    assert described.names == ["ting.nordlys.example.com", "alt.nordlys.example"]
    assert described.not_after == NOW + timedelta(days=90)


@pytest.mark.parametrize(("name", "host", "covers"), [
    ("*.nordlys.example.com", "ting.nordlys.example.com", True),
    ("*.nordlys.example.com", "a.ting.nordlys.example.com", False),
    ("*.nordlys.example.com", "nordlys.example.com", False),
    ("TING.nordlys.example.com", "ting.nordlys.example.com", True),
    ("ting.nordlys.example.com", "ting.nordlys.example.com.evil", False),
])
def test_wildcards_cover_one_level(name, host, covers) -> None:
    assert tls._covers(name, host) is covers


@pytest.mark.parametrize(("certificate", "said"), [
    (lambda: make_certificate("other.example"), "is for other.example, not"),
    (lambda: make_certificate("ting.nordlys.example.com", days=-1, starts=-30), "has expired"),
    (lambda: make_certificate("ting.nordlys.example.com", starts=2), "isn't valid yet"),
    (lambda: make_certificate(), "is for x, not"),
])
def test_a_certificate_that_wont_do_is_refused_plainly(certificate, said) -> None:
    chain, key = certificate()
    with pytest.raises(TlsError, match=said):
        tls.check_certificate(chain, key, "ting.nordlys.example.com", NOW)


def test_a_key_from_another_certificate_is_refused() -> None:
    chain, _ = make_certificate("ting.nordlys.example.com")
    _, other_key = make_certificate("ting.nordlys.example.com")
    with pytest.raises(TlsError, match="isn't this certificate's key"):
        tls.check_certificate(chain, other_key, "ting.nordlys.example.com", NOW)


def test_what_isnt_pem_is_refused() -> None:
    chain, key = make_certificate("ting.nordlys.example.com")
    with pytest.raises(TlsError, match="isn't a certificate"):
        tls.check_certificate("hello", key, "ting.nordlys.example.com", NOW)
    with pytest.raises(TlsError, match="isn't an unencrypted private key"):
        tls.check_certificate(chain, "hello", "ting.nordlys.example.com", NOW)
    locked = ec.generate_private_key(ec.SECP256R1()).private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.BestAvailableEncryption(b"secret")).decode()
    with pytest.raises(TlsError, match="isn't an unencrypted private key"):
        tls.check_certificate(chain, locked, "ting.nordlys.example.com", NOW)


def test_caddy_is_told_each_way(tls_dir) -> None:
    tls.write_for_caddy(TlsSettings())
    assert (tls_dir / "tls.caddy").read_text() == "tls internal\n"
    tls.write_for_caddy(TlsSettings(mode="acme", acme_email="it@nordlys.example"))
    assert (tls_dir / "tls.caddy").read_text() == "tls it@nordlys.example\n"
    chain, key = make_certificate("ting.nordlys.example.com")
    tls.write_for_caddy(TlsSettings(mode="own"), chain, key)
    assert (tls_dir / "tls.caddy").read_text() == (
        "tls /etc/caddy/ting/cert.pem /etc/caddy/ting/key.pem\n")
    assert (tls_dir / "cert.pem").read_text() == chain
    assert (tls_dir / "key.pem").stat().st_mode & 0o777 == 0o600
    assert not list(tls_dir.glob(".*.tmp"))


@pytest.mark.parametrize(("name", "public"), [
    ("ting.nordlys.example.com", True), ("reports.example.org", True),
    ("ting.nordlys.internal", False), ("ting.local", False), ("localhost", False),
    ("ting", False), ("10.0.0.5", False), ("ting.test", False), ("::1", False),
])
def test_lets_encrypt_is_only_for_names_on_the_internet(name, public) -> None:
    assert tls.public_name(name) is public


def test_the_console_goes_back_to_caddys_own_authority(tls_dir, engine, session,
                                                      monkeypatch, capsys) -> None:
    from app import console
    from app import db as db_module

    monkeypatch.setattr(db_module, "get_engine", lambda: engine)
    tls.save_tls(session, TlsSettings(mode="acme", acme_email="it@nordlys.example"))
    session.commit()
    tls.main()
    assert (tls_dir / "tls.caddy").read_text() == "tls it@nordlys.example\n"
    assert console.main(["reset-certificate"]) == 0
    assert "it was acme" in capsys.readouterr().out
    assert (tls_dir / "tls.caddy").read_text() == "tls internal\n"
    assert tls.load_tls(session).mode == "internal"
    logged = session.scalar(select(AuditEntry.action).order_by(AuditEntry.seq.desc()))
    assert logged == "tls.reset"


def test_an_own_certificate_whose_files_are_gone_falls_back(tls_dir, engine, session,
                                                           monkeypatch) -> None:
    from app import db as db_module

    monkeypatch.setattr(db_module, "get_engine", lambda: engine)
    tls.save_tls(session, TlsSettings(mode="own"))
    session.commit()
    tls.main()
    assert (tls_dir / "tls.caddy").read_text() == "tls internal\n"


# The admin panel


def test_uploading_a_certificate_needs_a_fresh_confirmation(client, admin, tls_dir,
                                                           session) -> None:
    _, headers = admin
    status = client.get(TLS, headers=headers).json()
    assert status["settings"]["mode"] == "internal" and status["root_url"] == "/ting-root.crt"
    chain, key = make_certificate("ting.nordlys.example.com", days=400, starts=-400)
    upload = {"mode": "own", "certificate_pem": chain, "key_pem": key}
    refused = client.put(TLS, headers=headers, json=upload)
    assert refused.headers["X-Ting-Reason"] == "step_up_required"
    assert not (tls_dir / "key.pem").exists()
    client.post("/api/auth/confirm-password", headers=headers, json={"password": PASSWORD})
    saved = client.put(TLS, headers=headers, json=upload)
    assert saved.status_code == 200, saved.text
    assert saved.json()["settings"]["certificate"]["subject"] == "ting.nordlys.example.com"
    assert saved.json()["root_url"] is None and "PRIVATE KEY" not in saved.text
    assert (tls_dir / "key.pem").read_text() == key
    logged = session.scalar(select(AuditEntry.details).where(AuditEntry.action == "tls.changed"))
    assert json.loads(logged)["certificate"] == "ting.nordlys.example.com"
    assert "PRIVATE" not in logged


def test_a_certificate_for_another_address_is_refused(client, admin, tls_dir) -> None:
    _, headers = admin
    client.post("/api/auth/confirm-password", headers=headers, json={"password": PASSWORD})
    chain, key = make_certificate("intranet.nordlys.example", days=400, starts=-400)
    refused = client.put(TLS, headers=headers,
                         json={"mode": "own", "certificate_pem": chain, "key_pem": key})
    assert refused.status_code == 400
    assert refused.json()["detail"] == (
        "The certificate is for intranet.nordlys.example, not ting.nordlys.example.com.")
    # Refused before the confirmation is used up.
    acme = client.put(TLS, headers=headers,
                      json={"mode": "acme", "acme_email": "it@nordlys.example"})
    assert acme.status_code == 200, acme.text
    assert (tls_dir / "tls.caddy").read_text() == "tls it@nordlys.example\n"


def test_own_mode_without_an_upload_keeps_the_one_uploaded(client, admin, tls_dir) -> None:
    _, headers = admin
    client.post("/api/auth/confirm-password", headers=headers, json={"password": PASSWORD})
    assert client.put(TLS, headers=headers, json={"mode": "own"}).status_code == 400
    chain, key = make_certificate("ting.nordlys.example.com", days=400, starts=-400)
    client.put(TLS, headers=headers, json={"mode": "own", "certificate_pem": chain,
                                            "key_pem": key})
    client.post("/api/auth/confirm-password", headers=headers, json={"password": PASSWORD})
    kept = client.put(TLS, headers=headers, json={"mode": "own"})
    assert kept.json()["settings"]["certificate"]["subject"] == "ting.nordlys.example.com"


def test_lets_encrypt_is_refused_for_a_private_address(client, admin, tls_dir,
                                                       monkeypatch) -> None:
    _, headers = admin
    monkeypatch.setattr(settings, "address", "https://ting.nordlys.internal")
    client.post("/api/auth/confirm-password", headers=headers, json={"password": PASSWORD})
    refused = client.put(TLS, headers=headers, json={"mode": "acme"})
    assert refused.status_code == 400 and "isn't one" in refused.json()["detail"]
    assert not (tls_dir / "tls.caddy").exists()


def test_an_acme_email_cannot_inject_caddy_settings(client, admin, tls_dir) -> None:
    _, headers = admin
    for sneaky in ("a@b.example\n}\nimport /etc/passwd", "a@b {", "x"):
        refused = client.put(TLS, headers=headers, json={"mode": "acme", "acme_email": sneaky})
        assert refused.status_code == 422, sneaky


# The admin panel's allowlist, at Caddy too


def allowlist_file() -> str:
    return (Path(settings.tls_dir) / tls.ALLOWLIST_FILE).read_text()


def test_caddy_is_told_the_admin_allowlist() -> None:
    tls.write_admin_allowlist(True, ("10.0.0.5", "192.168.1.0/24", "2001:db8::/32"))
    rule = allowlist_file()
    assert "\tpath /api/admin /api/admin/*\n" in rule
    assert "\tnot client_ip 10.0.0.5/32 192.168.1.0/24 2001:db8::/32\n" in rule
    assert rule.endswith('respond @outside_admin_allowlist "The admin panel can\'t be reached '
                         'from this address." 403\n')
    tls.write_admin_allowlist(False, ("10.0.0.5",))
    assert allowlist_file() == "# The admin panel's allowlist is off.\n"


def test_only_networks_reach_caddys_settings() -> None:
    with pytest.raises(ValueError):
        tls.write_admin_allowlist(True, ("10.0.0.0/8 } respond 200",))


def test_saving_the_allowlist_tells_caddy_and_the_reset_too(client, admin, session, engine,
                                                            monkeypatch) -> None:
    from starlette.testclient import TestClient

    from app import console
    from app import db as db_module
    from app.main import app

    _, headers = admin
    from_inside = TestClient(app, base_url="https://testserver", client=("10.0.0.5", 50000))
    current = from_inside.get("/api/admin/security", headers=headers).json()
    unchanged = {key: current[key] for key in (
        "min_password_length", "breach_check_enabled", "lockout_threshold", "lockout_minutes",
        "idle_timeout_minutes", "max_session_hours", "require_mfa_everyone",
        "require_mfa_administrators", "login_allowlist_enabled", "login_allowlist")}
    saved = from_inside.put("/api/admin/security", headers=headers, json=unchanged | {
        "admin_allowlist_enabled": True, "admin_allowlist": ["10.0.0.0/24"]})
    assert saved.status_code == 200, saved.text
    assert "not client_ip 10.0.0.0/24" in allowlist_file()

    monkeypatch.setattr(db_module, "get_engine", lambda: engine)
    assert console.main(["reset-allowlist"]) == 0
    assert allowlist_file() == "# The admin panel's allowlist is off.\n"


def test_the_app_tells_caddy_the_allowlist_as_it_starts(engine, session, monkeypatch) -> None:
    from app import db as db_module
    from app.policy import SecurityPolicy, save_policy

    monkeypatch.setattr(db_module, "get_engine", lambda: engine)
    save_policy(session, SecurityPolicy(admin_allowlist_enabled=True,
                                        admin_allowlist=("172.16.0.0/12",)))
    session.commit()
    tls.main()
    assert "not client_ip 172.16.0.0/12" in allowlist_file()


# Let's Encrypt through DNS

TOKEN = "cf_" + "a1B2" * 10
TSIG = "cWnu6Ju9zOki4f7Q+da2KKGo0KOXbCf6Pej6hW3geC4="


def test_caddy_is_told_the_cloudflare_dns_challenge(tls_dir) -> None:
    tls.write_for_caddy(
        TlsSettings(mode="acme", acme_email="it@nordlys.example", challenge="dns"),
        secrets={"cloudflare_token": TOKEN})
    assert (tls_dir / "tls.caddy").read_text() == (
        f"tls it@nordlys.example {{\n\tdns cloudflare {TOKEN}\n}}\n")
    assert (tls_dir / "tls.caddy").stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize(("server", "written"), [
    ("ns1.nordlys.example", "ns1.nordlys.example:53"),
    ("10.0.0.53:5353", "10.0.0.53:5353"),
    ("[2001:db8::53]", "[2001:db8::53]:53"),
    ("[2001:db8::53]:53", "[2001:db8::53]:53"),
])
def test_caddy_is_told_the_rfc2136_dns_challenge(tls_dir, server, written) -> None:
    tls.write_for_caddy(
        TlsSettings(mode="acme", challenge="dns", dns_provider="rfc2136", rfc2136_server=server,
                    rfc2136_key_name="ting-acme.", rfc2136_key_alg="hmac-sha512"),
        secrets={"rfc2136_key": TSIG})
    assert (tls_dir / "tls.caddy").read_text() == (
        "tls {\n\tdns rfc2136 {\n"
        '\t\tkey_name "ting-acme."\n\t\tkey_alg "hmac-sha512"\n'
        f'\t\tkey "{TSIG}"\n\t\tserver "{written}"\n\t}}\n}}\n')


@pytest.mark.parametrize("sneaky", [
    {"rfc2136_server": 'ns1" } import /etc/passwd {'},
    {"rfc2136_key_name": 'a"\n}'},
    {"acme_email": 'a@b" {'},
    {"cloudflare_token": "abc def } respond 200 {" + "x" * 20},
    {"rfc2136_key": 'AAAA" }'},
])
def test_nothing_can_slip_into_caddys_settings(sneaky) -> None:
    from pydantic import ValidationError

    from app.server_routes import TlsIn

    with pytest.raises(ValidationError):
        TlsIn(mode="acme", challenge="dns", **sneaky)


def test_the_dns_challenge_through_the_api(client, admin, tls_dir, session) -> None:
    _, headers = admin
    client.post("/api/auth/confirm-password", headers=headers, json={"password": PASSWORD})
    dns = {"mode": "acme", "challenge": "dns", "dns_provider": "cloudflare"}
    missing = client.put(TLS, headers=headers, json=dns)
    assert missing.status_code == 400 and "API token" in missing.json()["detail"]
    saved = client.put(TLS, headers=headers, json=dns | {"cloudflare_token": TOKEN})
    assert saved.status_code == 200, saved.text
    assert saved.json()["cloudflare_token_set"] and TOKEN not in saved.text
    assert TOKEN in (tls_dir / "tls.caddy").read_text()
    logged = session.scalar(select(AuditEntry.details).where(AuditEntry.action == "tls.changed"))
    session.commit()
    assert json.loads(logged) == {"mode": "acme", "challenge": "dns", "dns": "cloudflare"}
    # The token is kept when left out, and written again as the app starts.
    client.post("/api/auth/confirm-password", headers=headers, json={"password": PASSWORD})
    again = client.put(TLS, headers=headers, json=dns | {"acme_email": "it@nordlys.example"})
    assert again.status_code == 200 and again.json()["cloudflare_token_set"]
    (tls_dir / "tls.caddy").unlink()


def test_the_app_writes_the_dns_challenge_as_it_starts(tls_dir, engine, session,
                                                       monkeypatch) -> None:
    from app import db as db_module
    from app.sealed_settings import save_secrets

    monkeypatch.setattr(db_module, "get_engine", lambda: engine)
    tls.save_tls(session, TlsSettings(mode="acme", challenge="dns", dns_provider="rfc2136",
                                      rfc2136_server="ns1.nordlys.example",
                                      rfc2136_key_name="ting"))
    save_secrets(session, tls.SECRETS, {"rfc2136_key": TSIG})
    session.commit()
    tls.main()
    assert f'key "{TSIG}"' in (tls_dir / "tls.caddy").read_text()
