"""Keys kept in the data folder, wrapped by the master key.

They travel safely in backups: without /etc/ting/master.key they decrypt nothing.
The backup key also has a spare copy beside the master key, in /etc/ting/keys,
which the worker keeps in step: restoring on this server reads it when the data
folder is gone, so the recovery kit is needed only on a new server.
"""

from __future__ import annotations

import os
from pathlib import Path

from cryptography.exceptions import InvalidTag

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
    """The key backups are encrypted with. The wrapped copy here is inside the
    encrypted backups too, so restoring reads it from this folder or the spare copy
    (see kept_backup_key_path), or asks for it from the recovery kit."""
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


def kept_backup_key_path(master_key_path: str | Path) -> Path:
    """The backup key's spare copy: beside the master key, outside the data folder."""
    return Path(master_key_path).parent / "keys" / "backup.key.enc"


def keep_backup_key(data_dir: str | Path, master_key_path: str | Path) -> bool | None:
    """Bring the spare copy of the wrapped backup key in step with the data folder's.
    Returns True when it is, None when there's no backup key yet (before setup), and
    False when there's no folder for the copy. The folder is writable for the worker
    alone (deploy/docker-compose.yml)."""
    source = Path(data_dir) / "backup.key.enc"
    kept = kept_backup_key_path(master_key_path)
    if not source.exists():
        return None
    if not kept.parent.is_dir():
        return False
    wrapped = source.read_bytes()
    if kept.exists() and kept.read_bytes() == wrapped:
        return True
    tmp = kept.with_name(f".{kept.name}.{os.getpid()}.tmp")
    tmp.write_bytes(wrapped)
    tmp.chmod(0o600)
    tmp.replace(kept)
    return True


def backup_keys_on_server(data_dir: str | Path, master_key_path: str | Path
                          ) -> list[tuple[str, bytes]]:
    """The backup keys this server holds that the master key opens: the data
    folder's, then the spare copy's (the same key, unless one is out of step)."""
    master_key = load_master_key(master_key_path)
    found: list[tuple[str, bytes]] = []
    for where, path in (("the data folder", Path(data_dir) / "backup.key.enc"),
                        (str(kept_backup_key_path(master_key_path).parent),
                         kept_backup_key_path(master_key_path))):
        try:
            key = unwrap_key(master_key, path.read_bytes(), context=BACKUP_KEY_CONTEXT)
        except (OSError, ValueError, InvalidTag):
            continue
        if all(key != other for _, other in found):
            found.append((where, key))
    return found

