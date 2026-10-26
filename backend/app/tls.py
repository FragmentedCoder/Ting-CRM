"""HTTPS: which certificate Caddy serves for Þing's address (and the admin
panel's allowlist, the other setting the app hands Caddy).

Three ways, chosen in the setup wizard or Admin -> Certificate:

- Caddy's own certificate authority (the default). Each computer that uses
  Þing trusts it once its root certificate is installed; Caddy serves that
  at /ting-root.crt.
- The organisation's own certificate: a PEM chain and its key, checked here to
  match each other, be valid now and cover the address.
- Let's Encrypt: checked over the internet on port 443, or, for a server the
  internet can't reach, through DNS (Cloudflare, or the organisation's own DNS
  server by RFC 2136), whose credentials are sealed in the database and written
  only into Caddy's settings.

The app writes Caddy a small file (tls.caddy, and the certificate and key when
there are some) into a volume the two share; Caddy copies it into place and
reloads when it changes, and keeps what it had if the new settings fail. The key
lives only in that volume, never in the database, so after a restore elsewhere
the certificate is uploaded again.
"""

from __future__ import annotations

import ipaddress
import os
import re
import socket
import ssl
from datetime import datetime
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.x509.oid import NameOID
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import clock
from app.policy import Setting
from app.settings import settings

TLS_SETTING = "tls/settings"
# Where Caddy finds them (the same volume, mounted read-only there).
CADDY_DIR = "/etc/caddy/ting"

Mode = Literal["internal", "own", "acme"]
# How Let's Encrypt checks the address: over the internet on port 443, or through
# DNS, for a server the internet can't reach.
Challenge = Literal["tls-alpn", "dns"]
DnsProvider = Literal["cloudflare", "rfc2136"]
KeyAlgorithm = Literal["hmac-sha256", "hmac-sha384", "hmac-sha512", "hmac-sha224", "hmac-sha1"]
# The DNS credentials, sealed with the config key: cloudflare_token, rfc2136_key.
SECRETS = "tls"
# What may go into Caddy's settings, and nothing else: no spaces, quotes or braces.
CLOUDFLARE_TOKEN = r"^[A-Za-z0-9_-]{20,200}$"
TSIG_KEY = r"^[A-Za-z0-9+/]{16,600}={0,2}$"


class Certificate(BaseModel):
    subject: str
    names: list[str]
    issuer: str
    not_after: datetime


class TlsSettings(BaseModel):
    mode: Mode = "internal"
    acme_email: str = Field(default="", max_length=254, pattern=r"^([^@\s{}\"]+@[^@\s{}\"]+)?$")
    challenge: Challenge = "tls-alpn"
    dns_provider: DnsProvider = "cloudflare"
    # The DNS server that takes RFC 2136 updates (host, or host:port; 53 if left out).
    rfc2136_server: str = Field(default="", max_length=260,
                                pattern=r"^(([A-Za-z0-9.-]+|\[[0-9A-Fa-f:]+\])(:[0-9]{1,5})?)?$")
    rfc2136_key_name: str = Field(default="", max_length=253, pattern=r"^[A-Za-z0-9._-]*$")
    rfc2136_key_alg: KeyAlgorithm = "hmac-sha256"
    # What was uploaded, to show it (the files themselves are Caddy's).
    certificate: Certificate | None = None

    def dns_missing(self, secrets: dict[str, object]) -> str | None:
        """What the DNS challenge still needs, in words, or None."""
        if self.mode != "acme" or self.challenge != "dns":
            return None
        if self.dns_provider == "cloudflare" and not secrets.get("cloudflare_token"):
            return "Cloudflare needs an API token that may edit the zone's DNS."
        if self.dns_provider == "rfc2136" and not (
                self.rfc2136_server and self.rfc2136_key_name and secrets.get("rfc2136_key")):
            return "Your DNS server needs its address, the TSIG key's name and the key."
        return None


class TlsError(Exception):
    """A certificate or setting that won't do, said plainly."""


def host() -> str:
    return urlsplit(settings.address).hostname or "localhost"


# Names Let's Encrypt never issues for: they aren't on the public internet.
PRIVATE_SUFFIXES = (".local", ".internal", ".lan", ".home.arpa", ".test", ".localhost",
                    ".example", ".invalid", ".corp", ".intranet")


def public_name(name: str) -> bool:
    name = name.lower().rstrip(".")
    try:
        ipaddress.ip_address(name)
        return False
    except ValueError:
        pass
    return "." in name and not any(f".{name}".endswith(suffix) for suffix in PRIVATE_SUFFIXES)


def load_tls(db: Session) -> TlsSettings:
    stored = db.scalar(select(Setting.value).where(Setting.key == TLS_SETTING))
    return TlsSettings.model_validate_json(stored) if stored else TlsSettings()


def _covers(name: str, wanted: str) -> bool:
    name, wanted = name.lower().rstrip("."), wanted.lower().rstrip(".")
    if name.startswith("*."):
        return wanted.count(".") == name.count(".") and wanted.endswith(name[1:])
    return name == wanted


def _describe(cert: x509.Certificate) -> Certificate:
    try:
        names = cert.extensions.get_extension_for_class(
            x509.SubjectAlternativeName).value.get_values_for_type(x509.DNSName)
    except x509.ExtensionNotFound:
        names = []
    common = cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
    issuer = cert.issuer.get_attributes_for_oid(NameOID.COMMON_NAME)
    return Certificate(
        # Caddy's own certificates name the address only among the names.
        subject=str(common[0].value) if common else (names[0] if names else
                                                     cert.subject.rfc4514_string()),
        names=names,
        issuer=str(issuer[0].value) if issuer else cert.issuer.rfc4514_string(),
        not_after=cert.not_valid_after_utc,
    )


def check_certificate(chain_pem: str, key_pem: str, address_host: str,
                      now: datetime | None = None) -> Certificate:
    """The leaf certificate described, if the chain and key will do for the address."""
    now = now or clock.utcnow()
    try:
        chain = x509.load_pem_x509_certificates(chain_pem.encode())
    except ValueError as exc:
        raise TlsError("That isn't a certificate in PEM form (-----BEGIN CERTIFICATE-----).") \
            from exc
    try:
        key = serialization.load_pem_private_key(key_pem.encode(), password=None)
    except (ValueError, TypeError) as exc:
        raise TlsError("That isn't an unencrypted private key in PEM form.") from exc
    leaf = chain[0]
    same = serialization.PublicFormat.SubjectPublicKeyInfo
    if (key.public_key().public_bytes(serialization.Encoding.DER, same)
            != leaf.public_key().public_bytes(serialization.Encoding.DER, same)):
        raise TlsError("The key isn't this certificate's key.")
    if leaf.not_valid_after_utc <= now:
        raise TlsError("The certificate has expired.")
    if leaf.not_valid_before_utc > now:
        raise TlsError("The certificate isn't valid yet.")
    described = _describe(leaf)
    if not any(_covers(name, address_host) for name in described.names):
        raise TlsError(f"The certificate is for {', '.join(described.names) or described.subject}"
                       f", not {address_host}.")
    return described


def _write(path: Path, content: str, mode: int = 0o644) -> None:
    """Whole or not at all: Caddy may be reading."""
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(content)
    tmp.chmod(mode)
    os.replace(tmp, path)


def _dns_block(tls: TlsSettings, secrets: dict[str, object]) -> str:
    """The tls block for the DNS challenge, its values checked once more: they go
    into Caddy's settings as they are."""
    if tls.dns_provider == "cloudflare":
        token = str(secrets.get("cloudflare_token", ""))
        if not re.fullmatch(CLOUDFLARE_TOKEN, token):
            raise TlsError("That isn't a Cloudflare API token.")
        return f"\tdns cloudflare {token}\n"
    key = str(secrets.get("rfc2136_key", ""))
    if not re.fullmatch(TSIG_KEY, key):
        raise TlsError("That isn't a TSIG key (base64, as the DNS server gives it).")
    server = tls.rfc2136_server
    if not re.search(r":[0-9]+$", server):  # no port given: DNS's own
        server += ":53"
    return (f"\tdns rfc2136 {{\n"
            f'\t\tkey_name "{tls.rfc2136_key_name}"\n'
            f'\t\tkey_alg "{tls.rfc2136_key_alg}"\n'
            f'\t\tkey "{key}"\n'
            f'\t\tserver "{server}"\n'
            "\t}\n")


def write_for_caddy(tls: TlsSettings, chain_pem: str | None = None,
                    key_pem: str | None = None, secrets: dict[str, object] | None = None) -> None:
    """Give Caddy its TLS settings (and files, for an own certificate)."""
    folder = Path(settings.tls_dir)
    folder.mkdir(parents=True, exist_ok=True)
    mode = 0o644
    if tls.mode == "own":
        if chain_pem is not None and key_pem is not None:
            _write(folder / "key.pem", key_pem, 0o600)
            _write(folder / "cert.pem", chain_pem)
        directive = f"tls {CADDY_DIR}/cert.pem {CADDY_DIR}/key.pem"
    elif tls.mode == "acme" and tls.challenge == "dns":
        # The DNS credentials are in it: Caddy's (root) and the app's to read only.
        mode = 0o600
        email = f" {tls.acme_email}" if tls.acme_email else ""
        directive = f"tls{email} {{\n{_dns_block(tls, secrets or {})}}}"
    elif tls.mode == "acme":
        # Caddy's automatic HTTPS is Let's Encrypt; the email is for expiry notices.
        directive = f"tls {tls.acme_email}" if tls.acme_email else "# Let's Encrypt"
    else:
        directive = "tls internal"
    _write(folder / "tls.caddy", directive + "\n", mode)


ALLOWLIST_FILE = "admin-allowlist.caddy"


def write_admin_allowlist(enabled: bool, networks: tuple[str, ...]) -> None:
    """Give Caddy the admin panel's allowlist, so requests to the admin API from
    elsewhere stop there as well as in the app. Only networks Python reads as such
    are written: nothing else reaches Caddy's settings."""
    folder = Path(settings.tls_dir)
    folder.mkdir(parents=True, exist_ok=True)
    if not enabled:
        _write(folder / ALLOWLIST_FILE, "# The admin panel's allowlist is off.\n")
        return
    ranges = " ".join(str(ipaddress.ip_network(net, strict=False)) for net in networks)
    outside = f"\tnot client_ip {ranges}\n" if ranges else ""
    _write(folder / ALLOWLIST_FILE, (
        "# The admin panel's allowlist, written by Þing (Admin -> Security).\n"
        "@outside_admin_allowlist {\n"
        "\tpath /api/admin /api/admin/*\n"
        f"{outside}"
        "}\n"
        'respond @outside_admin_allowlist "The admin panel can\'t be reached from this '
        'address." 403\n'))


def save_tls(db: Session, tls: TlsSettings) -> None:
    db.merge(Setting(key=TLS_SETTING, value=tls.model_dump_json()))


def served_certificate(timeout: float = 5) -> Certificate | None:
    """What Caddy serves for the address right now, asked of Caddy itself."""
    port = urlsplit(settings.address).port or 443
    # Only to read the certificate Caddy serves, so it isn't checked here.
    context = ssl.create_default_context()
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    try:
        with socket.create_connection((settings.caddy_host, port), timeout=timeout) as raw:
            with context.wrap_socket(raw, server_hostname=host()) as tls_socket:
                der = tls_socket.getpeercert(binary_form=True)
    except OSError:
        return None
    return _describe(x509.load_der_x509_certificate(der)) if der else None


def main() -> None:
    """Write Caddy's settings from what's saved (the app does this as it starts).
    An own certificate whose files are gone (a restore elsewhere) falls back to
    Caddy's own authority until it's uploaded again."""
    from sqlalchemy.orm import Session as _Session

    from app.db import get_engine
    from app.policy import load_policy
    from app.sealed_settings import load_secrets

    with _Session(get_engine()) as db:
        tls = load_tls(db)
        policy = load_policy(db)
        secrets = load_secrets(db, SECRETS) if tls.challenge == "dns" else {}
    write_admin_allowlist(policy.admin_allowlist_enabled, policy.admin_allowlist)
    if tls.mode == "own" and not (Path(settings.tls_dir) / "cert.pem").exists():
        print("The certificate's files are missing: serving Caddy's own until it's "
              "uploaded again (Admin -> Certificate).", flush=True)
        tls = TlsSettings()
    write_for_caddy(tls, secrets=secrets)


if __name__ == "__main__":
    main()
