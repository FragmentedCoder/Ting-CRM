"""Checking a new password against Have I Been Pwned's Pwned Passwords range API.

Only the first 5 characters of the password's SHA-1 leave the server (k-anonymity),
and the reply is padded with decoys, so its size says nothing about the answer.
"""

from __future__ import annotations

import hashlib

import httpx

RANGE_URL = "https://api.pwnedpasswords.com/range/{prefix}"
TIMEOUT_SECONDS = 5.0
USER_AGENT = "Ting-CRM (+https://github.com/FragmentedCoder/Ting-CRM)"


class BreachCheckUnavailable(RuntimeError):
    """The service couldn't be reached; the password was neither accepted nor rejected."""


def _client() -> httpx.Client:
    return httpx.Client(
        timeout=TIMEOUT_SECONDS,
        headers={"Add-Padding": "true", "User-Agent": USER_AGENT},
    )


def _fetch_range(prefix: str) -> str:
    try:
        with _client() as client:
            response = client.get(RANGE_URL.format(prefix=prefix))
            response.raise_for_status()
            return response.text
    except httpx.HTTPError as exc:
        raise BreachCheckUnavailable(
            "Couldn't check the password against known data breaches."
        ) from exc


def times_breached(password: str) -> int:
    """How often the password appears in known breaches; 0 if never."""
    digest = hashlib.sha1(password.encode(), usedforsecurity=False).hexdigest().upper()
    prefix, suffix = digest[:5], digest[5:]
    for line in _fetch_range(prefix).splitlines():
        candidate, _, count = line.partition(":")
        if candidate.strip() == suffix:
            return int(count)
    return 0


def reachable() -> bool:
    """Whether the range API answers, for the server health page."""
    try:
        _fetch_range("00000")
    except BreachCheckUnavailable:
        return False
    return True
