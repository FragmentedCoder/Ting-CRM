"""Replacing the master key, and moving data made under one master key to another.

What the master key protects are wrapped keys: the database, backup and config
keys in the data folder, and each customer's key in the database. Rotating it
unwraps each with the old master key and wraps it again with a new one. Nothing
those keys encrypt changes, so it takes moments. Restoring a backup made before a
rotation does the same, from that backup's master key to the server's.

`ting keys rotate` runs it with Þing stopped, in steps that can each be
finished or undone if the server stops halfway:

1. The new master key goes to master.key.next, and the key files, wrapped again,
   to <name>.next beside them.
2. One transaction wraps every customer key again, records the rotation (the
   setting "keys/rotation", naming the new key) and logs it.
3. The .next files replace the key files, and master.key.next the master key.
4. The record goes.

Stopped before step 2 committed, a rotation is undone; after, it's finished.
Þing won't start while one is unfinished.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path

from cryptography.exceptions import InvalidTag
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app import audit, clock
from app.crypto.key_files import BACKUP_KEY_CONTEXT, CONFIG_KEY_CONTEXT, DATABASE_KEY_CONTEXT
from app.crypto.keys import generate_key, load_master_key, unwrap_key, wrap_key
from app.customers import Customer, customer_key_context
from app.db import make_engine
from app.policy import Setting

KEY_FILES = {
    "db.key.enc": DATABASE_KEY_CONTEXT,
    "backup.key.enc": BACKUP_KEY_CONTEXT,
    "config.key.enc": CONFIG_KEY_CONTEXT,
}
ROTATION_SETTING = "keys/rotation"


class RotationError(Exception):
    """A rotation that can't go ahead, said plainly."""


@dataclass
class Rotated:
    old_id: str
    new_id: str
    new_key: bytes
    customer_keys: int


def key_id(key: bytes) -> str:
    """A name for a master key that gives nothing of it away, such as 3F9A-12BC-77D0:
    ting status shows it, and each backup's manifest records it."""
    digest = hashlib.sha256(b"ting/master-key-id/" + key).hexdigest()[:12].upper()
    return "-".join(digest[i : i + 4] for i in range(0, 12, 4))


def _next(path: Path) -> Path:
    return path.with_name(f"{path.name}.next")


def _write(path: Path, data: bytes) -> None:
    """Whole or not at all, and on disk before anything depends on it."""
    tmp = path.with_name(f".{path.name}.tmp")
    with open(tmp, "wb") as file:
        file.write(data)
        file.flush()
        os.fsync(file.fileno())
    tmp.chmod(0o600)
    os.replace(tmp, path)


def opens(folder: Path, master_key: bytes) -> bool:
    """Whether this master key opens the database key in folder."""
    try:
        unwrap_key(master_key, (folder / "db.key.enc").read_bytes(), context=DATABASE_KEY_CONTEXT)
    except (InvalidTag, ValueError):
        return False
    return True


def rewrap_key_files(folder: Path, old: bytes, new: bytes, suffix: str = "") -> None:
    """Each key file in folder, wrapped with new instead of old, written to its name
    plus suffix (over it, without one)."""
    for name, context in KEY_FILES.items():
        path = folder / name
        if path.exists():
            plain = unwrap_key(old, path.read_bytes(), context=context)
            _write(folder / f"{name}{suffix}", wrap_key(new, plain, context=context))


def rewrap_customer_keys(db: Session, old: bytes, new: bytes) -> int:
    customers = list(db.scalars(select(Customer)))
    for customer in customers:
        context = customer_key_context(customer.id)
        plain = unwrap_key(old, customer.wrapped_key, context=context)
        customer.wrapped_key = wrap_key(new, plain, context=context)
    return len(customers)


def pending(master_key_path: str | Path) -> bool:
    """Whether a rotation stopped halfway (Þing won't start until it's resumed)."""
    return _next(Path(master_key_path)).exists()


def rotate(data_dir: str | Path, master_key_path: str | Path) -> Rotated:
    """Replace the master key. Þing must be stopped."""
    data_dir, path = Path(data_dir), Path(master_key_path)
    if pending(path):
        raise RotationError("A rotation is unfinished: resume it first.")
    old = load_master_key(path)
    if not opens(data_dir, old):
        raise RotationError("The master key in place doesn't open this data.")
    new = generate_key()
    committed = False
    try:
        _write(_next(path), new)
        rewrap_key_files(data_dir, old, new, ".next")
        engine = make_engine(data_dir, path)
        try:
            with Session(engine) as db:
                count = rewrap_customer_keys(db, old, new)
                db.merge(Setting(key=ROTATION_SETTING, value=json.dumps(
                    {"to": key_id(new), "at": clock.utcnow().isoformat()})))
                audit.append(db, "keys.master_rotated", actor_name="console", details={
                    "from": key_id(old), "to": key_id(new), "customer_keys": count})
                db.commit()
                committed = True
        finally:
            engine.dispose()
    except BaseException:
        if not committed:
            _undo(data_dir, path)  # as if it never began
        raise  # after the commit, resume() finishes it
    _finish(data_dir, path)
    return Rotated(key_id(old), key_id(new), new, count)


def _finish(data_dir: Path, path: Path) -> None:
    for name in KEY_FILES:
        if _next(data_dir / name).exists():
            os.replace(_next(data_dir / name), data_dir / name)
    os.replace(_next(path), path)
    engine = make_engine(data_dir, path)
    try:
        with Session(engine) as db:
            db.execute(delete(Setting).where(Setting.key == ROTATION_SETTING))
            db.commit()
    finally:
        engine.dispose()


def _undo(data_dir: Path, path: Path) -> None:
    for name in KEY_FILES:
        _next(data_dir / name).unlink(missing_ok=True)
    _next(path).unlink(missing_ok=True)


def resume(data_dir: str | Path, master_key_path: str | Path) -> str | None:
    """Finish or undo a rotation that stopped halfway: "finished", "undone", or None
    when there was none."""
    data_dir, path = Path(data_dir), Path(master_key_path)
    if not pending(path):
        return None
    new = load_master_key(_next(path))
    # The key files may already be wrapped with the new key (stopped in step 3).
    opener = path if opens(data_dir, load_master_key(path)) else _next(path)
    if not opens(data_dir, load_master_key(opener)):
        raise RotationError("Neither the master key nor the new one opens this data.")
    engine = make_engine(data_dir, opener)
    try:
        with Session(engine) as db:
            record = db.scalar(select(Setting.value).where(Setting.key == ROTATION_SETTING))
            db.commit()
    finally:
        engine.dispose()
    # A record left by an earlier rotation names another key: this one never committed.
    if record is not None and json.loads(record).get("to") == key_id(new):
        _finish(data_dir, path)
        return "finished"
    _undo(data_dir, path)
    return "undone"


def rewrap_restored(folder: Path, old: bytes, master_key_path: str | Path) -> int:
    """Move a restored copy made under an older master key to the server's own.
    Returns how many customer keys were wrapped again."""
    current = load_master_key(master_key_path)
    rewrap_key_files(folder, old, current)
    engine = make_engine(folder, master_key_path)
    try:
        with Session(engine) as db:
            count = rewrap_customer_keys(db, old, current)
            audit.append(db, "keys.restored_under_current_master_key", actor_name="console",
                         details={"from": key_id(old), "to": key_id(current),
                                  "customer_keys": count})
            db.commit()
    finally:
        engine.dispose()
    return count
