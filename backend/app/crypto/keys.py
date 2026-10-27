"""Envelope encryption for Þing's key hierarchy (see docs/architecture.md).

The master key never leaves /etc/ting; every other key (database,
per-customer, backup) is generated at random and stored only in its
wrapped form, decryptable solely by whoever holds the master key.
"""

from __future__ import annotations

import base64
import os
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

KEY_LENGTH = 32
NONCE_LENGTH = 12


def generate_key() -> bytes:
    """A fresh random 256-bit key, suitable for a database, customer or backup key."""
    return os.urandom(KEY_LENGTH)


def load_master_key(path: str | Path) -> bytes:
    data = Path(path).read_bytes()
    if len(data) != KEY_LENGTH:
        raise ValueError(f"Master key at {path} must be {KEY_LENGTH} bytes, found {len(data)}.")
    return data


def to_kit_text(key: bytes) -> str:
    """A key as it is written in the recovery kit: base32, in groups of four."""
    text = base64.b32encode(key).decode().rstrip("=")
    return " ".join(text[i : i + 4] for i in range(0, len(text), 4))


def from_kit_text(text: str) -> bytes:
    """Read a key back from the recovery kit, forgiving spaces, dashes and case."""
    compact = text.upper().replace(" ", "").replace("-", "")
    return base64.b32decode(compact + "=" * (-len(compact) % 8))


def wrap_key(master_key: bytes, plaintext_key: bytes, *, context: bytes) -> bytes:
    """Encrypt plaintext_key under the master key, bound to context (what the key is for).

    The same context must be given to unwrap it, so a wrapped key moved onto
    another record, such as another customer, will not open.
    """
    nonce = os.urandom(NONCE_LENGTH)
    return nonce + AESGCM(master_key).encrypt(nonce, plaintext_key, context)


def unwrap_key(master_key: bytes, wrapped: bytes, *, context: bytes) -> bytes:
    """Reverse wrap_key. Raises cryptography.exceptions.InvalidTag if wrapped was tampered
    with, or was wrapped for a different context."""
    nonce, ciphertext = wrapped[:NONCE_LENGTH], wrapped[NONCE_LENGTH:]
    return AESGCM(master_key).decrypt(nonce, ciphertext, context)
