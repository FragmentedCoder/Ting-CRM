"""Settings that hold secrets, such as a backup target's or the mail server's password.

The database is encrypted already; these are sealed again, with the config key
(wrapped by the master key, like the database key), so a copy of the settings
table, an export or a page that shows settings never shows them. They're read
only where they're used, and never sent to the browser.
"""

from __future__ import annotations

import base64
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.crypto.key_files import load_or_create_config_key
from app.crypto.sealing import seal, unseal
from app.policy import Setting
from app.settings import settings


def _key() -> bytes:
    return load_or_create_config_key(settings.data_dir, settings.master_key_path)


def _bound(name: str) -> bytes:
    return f"ting/setting/{name}".encode()


def save_secrets(db: Session, name: str, values: dict[str, Any]) -> None:
    """Seal and keep these values under a name, in the caller's transaction."""
    sealed = seal(_key(), values, bound_to=_bound(name))
    db.merge(Setting(key=f"secret/{name}", value=base64.b64encode(sealed).decode()))


def load_secrets(db: Session, name: str) -> dict[str, Any]:
    """The values kept under a name, or an empty dict if there are none."""
    stored = db.scalar(select(Setting.value).where(Setting.key == f"secret/{name}"))
    if stored is None:
        return {}
    return unseal(_key(), base64.b64decode(stored), bound_to=_bound(name))
