"""Password hashing and the password rules (ASVS 5.0, V6.2).

No composition rules (upper case, digits, symbols): ASVS forbids them, because
they push people towards predictable patterns. Length and context checks only.
"""

from __future__ import annotations

import re
import unicodedata

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from app.policy import SecurityPolicy

MAX_PASSWORD_LENGTH = 256

# Argon2id with argon2-cffi's defaults: RFC 9106's low-memory profile (64 MiB, 3 passes).
_hasher = PasswordHasher()


class PasswordRejected(ValueError):
    """The password breaks a rule; the message is fit to show the user."""


def normalize_password(password: str) -> str:
    # The same password typed on different keyboards or systems must match.
    return unicodedata.normalize("NFKC", password)


def hash_password(password: str) -> str:
    return _hasher.hash(normalize_password(password))


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, normalize_password(password))
    except (VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


_DUMMY_HASH = _hasher.hash("never a valid Þing password")

# "þing" anywhere, but "ting" and "thing" only as words of their own: inside other
# words ("meeting", "something") they say nothing about the product.
_PRODUCT_NAME = re.compile(r"þing|(?<![^\W\d_])th?ing(?![^\W\d_])")


def burn_verify_time(password: str) -> None:
    """Take as long as a real check, so an unknown username answers no faster than a known one."""
    verify_password(_DUMMY_HASH, password)


def check_password(password: str, policy: SecurityPolicy, *, username: str) -> None:
    """The local rules only; users.vet_new_password adds the breach check."""
    normalized = normalize_password(password)
    if len(normalized) < policy.min_password_length:
        raise PasswordRejected(f"Use at least {policy.min_password_length} characters.")
    if len(normalized) > MAX_PASSWORD_LENGTH:
        raise PasswordRejected(f"Use at most {MAX_PASSWORD_LENGTH} characters.")
    lowered = normalized.casefold()
    username = username.casefold()
    if (len(username) >= 3 and username in lowered) or _PRODUCT_NAME.search(lowered):
        raise PasswordRejected("Don't use your username or the product name in your password.")
