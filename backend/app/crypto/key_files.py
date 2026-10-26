"""Keys kept in the data folder, wrapped by the master key.

They travel safely in backups: without /etc/ting/master.key they decrypt nothing.
"""

from __future__ import annotations

import os
from pathlib import Path

from app.crypto.keys import generate_key, load_master_key, unwrap_key, wrap_key

DATABASE_KEY_CONTEXT = b"ting/database-key"
BACKUP_KEY_CONTEXT = b"ting/backup-key"
CONFIG_KEY_CONTEXT = b"ting/config-key"


def load_or_create_wrapped_key(
    wrapped_path: Path, master_key_path: str | Path, context: bytes
) -> bytes:
    master_key = load_master_key(master_key_path)
    if not wrapped_path.exists():
        _create_once(wrapped_path, wrap_key(master_key, generate_key(), context=context))
    return unwrap_key(master_key, wrapped_path.read_bytes(), context=context)


def load_or_create_database_key(data_dir: str | Path, master_key_path: str | Path) -> bytes:
    """The key that opens the SQLCipher database."""
    return load_or_create_wrapped_key(
        Path(data_dir) / "db.key.enc", master_key_path, DATABASE_KEY_CONTEXT
    )


def load_or_create_backup_key(data_dir: str | Path, master_key_path: str | Path) -> bytes:
    """The key backups are encrypted with. Restoring needs it from the recovery kit,
    since the wrapped copy is inside the encrypted backups themselves."""
    return load_or_create_wrapped_key(
        Path(data_dir) / "backup.key.enc", master_key_path, BACKUP_KEY_CONTEXT
    )


def load_or_create_config_key(data_dir: str | Path, master_key_path: str | Path) -> bytes:
    """The key that seals secrets in settings, such as a backup target's password."""
    return load_or_create_wrapped_key(
        Path(data_dir) / "config.key.enc", master_key_path, CONFIG_KEY_CONTEXT
    )


def _create_once(path: Path, data: bytes) -> None:
    """Write data to path unless it already exists.

    The app and the worker can start at the same moment on a fresh install. If
    each wrote its own key, the database would be created under one key and the
    other would be left on disk, and the database could never be opened again.
    A hard link either creates the file whole or fails, so the first one wins
    and everyone reads the winner's key back.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_bytes(data)
    tmp.chmod(0o600)
    try:
        os.link(tmp, path)
    except FileExistsError:
        pass
    finally:
        tmp.unlink()
