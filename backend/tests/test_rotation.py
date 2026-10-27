import json
import re

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import clock
from app.audit import AuditEntry, verify
from app.crypto import rotation
from app.crypto.key_files import load_or_create_backup_key
from app.crypto.keys import load_master_key
from app.crypto.rotation import RotationError, key_id
from app.customers import Customer, Keyring
from app.db import make_engine
from app.policy import Setting
from app.sealed_settings import load_secrets, save_secrets

FILES = ("db.key.enc", "backup.key.enc", "config.key.enc")


@pytest.fixture
def stocked(session, data_dir, master_key_path):
    """Two customers with sealed details, a sealed setting and the backup key (setup
    makes it): what the master key protects, by way of the keys it wraps."""
    load_or_create_backup_key(data_dir, master_key_path)
    keyring = Keyring()
    for name in ("Fjordlys Energi A/S", "Nordlys IT ApS"):
        customer = Customer(wrapped_key=b"", sealed=b"", retention_months=24,
                            created_at=clock.utcnow())
        session.add(customer)
        session.flush()
        customer.sealed = keyring.give_new_key(customer).seal(
            "customer", customer.id, {"name": name, "cvr": "12345678", "address": ""})
    save_secrets(session, "mail", {"password": "mail secret"})
    session.commit()
    return session


def readable(data_dir, master_key_path) -> list[str]:
    """Everything, read back with the master key in place."""
    engine = make_engine(data_dir, master_key_path)
    try:
        with Session(engine) as db:
            keyring = Keyring()
            names = [keyring.name(c) for c in db.scalars(select(Customer).order_by(Customer.id))]
            assert load_secrets(db, "mail") == {"password": "mail secret"}
            assert verify(db).ok
            db.commit()
            return names
    finally:
        engine.dispose()


def leftovers(data_dir, master_key_path) -> list[str]:
    folders = (data_dir, master_key_path.parent)
    return sorted(p.name for folder in folders for p in folder.iterdir()
                  if p.name.endswith((".next", ".tmp")))


def test_a_key_id_names_a_key_without_giving_it_away() -> None:
    key = bytes(range(32))
    assert re.fullmatch(r"[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}", key_id(key))
    assert key_id(key) == key_id(bytes(range(32))) != key_id(bytes(32))


def test_rotating_wraps_every_key_again_and_reads_the_same(stocked, engine, data_dir,
                                                           master_key_path) -> None:
    engine.dispose()
    old = master_key_path.read_bytes()
    before = {name: (data_dir / name).read_bytes() for name in FILES}

    done = rotation.rotate(data_dir, master_key_path)

    new = master_key_path.read_bytes()
    assert new != old and new == done.new_key and len(new) == 32
    assert (done.old_id, done.new_id, done.customer_keys) == (key_id(old), key_id(new), 2)
    assert all((data_dir / name).read_bytes() != before[name] for name in FILES)
    assert not rotation.opens(data_dir, old) and rotation.opens(data_dir, new)
    assert readable(data_dir, master_key_path) == ["Fjordlys Energi A/S", "Nordlys IT ApS"]
    assert leftovers(data_dir, master_key_path) == []
    assert oct(master_key_path.stat().st_mode & 0o777) == "0o600"
    engine = make_engine(data_dir, master_key_path)
    with Session(engine) as db:
        logged = db.scalar(select(AuditEntry).where(AuditEntry.action == "keys.master_rotated"))
        assert json.loads(logged.details) == {
            "customer_keys": 2, "from": key_id(old), "to": key_id(new)}
        assert db.get(Setting, rotation.ROTATION_SETTING) is None
    engine.dispose()


def test_a_rotation_that_fails_before_committing_is_undone(stocked, engine, data_dir,
                                                           master_key_path, monkeypatch) -> None:
    engine.dispose()
    old = master_key_path.read_bytes()

    def broken(db, old, new):
        raise RuntimeError("the disk is full")

    monkeypatch.setattr(rotation, "rewrap_customer_keys", broken)
    with pytest.raises(RuntimeError):
        rotation.rotate(data_dir, master_key_path)
    assert master_key_path.read_bytes() == old
    assert not rotation.pending(master_key_path) and leftovers(data_dir, master_key_path) == []
    assert readable(data_dir, master_key_path) == ["Fjordlys Energi A/S", "Nordlys IT ApS"]


@pytest.mark.parametrize("swapped", [(), ("db.key.enc",), ("db.key.enc", "backup.key.enc")])
def test_a_rotation_stopped_after_committing_is_finished(stocked, engine, data_dir,
                                                         master_key_path, monkeypatch,
                                                         swapped) -> None:
    """Stopped in step 3, with none or some of the key files already swapped."""
    engine.dispose()

    def power_cut(data_dir, path):
        for name in swapped:
            (data_dir / f"{name}.next").replace(data_dir / name)
        raise SystemExit("power cut")

    finish = rotation._finish
    monkeypatch.setattr(rotation, "_finish", power_cut)
    with pytest.raises(SystemExit):
        rotation.rotate(data_dir, master_key_path)
    monkeypatch.setattr(rotation, "_finish", finish)
    new = load_master_key(master_key_path.with_name("master.key.next"))
    assert rotation.pending(master_key_path)

    assert rotation.resume(data_dir, master_key_path) == "finished"
    assert master_key_path.read_bytes() == new
    assert not rotation.pending(master_key_path) and leftovers(data_dir, master_key_path) == []
    assert readable(data_dir, master_key_path) == ["Fjordlys Energi A/S", "Nordlys IT ApS"]


def test_a_rotation_stopped_before_committing_is_undone(stocked, engine, data_dir,
                                                        master_key_path) -> None:
    """Stopped in step 1: a new key and some key files written, nothing committed. A
    record an earlier rotation left behind names another key and changes nothing."""
    engine.dispose()
    old = master_key_path.read_bytes()
    with Session(make_engine(data_dir, master_key_path)) as db:
        db.merge(Setting(key=rotation.ROTATION_SETTING, value=json.dumps({"to": "AAAA-BBBB-CCCC"})))
        db.commit()
    new = bytes(range(32))
    rotation._write(master_key_path.with_name("master.key.next"), new)
    rotation.rewrap_key_files(data_dir, old, new, ".next")

    assert rotation.resume(data_dir, master_key_path) == "undone"
    assert master_key_path.read_bytes() == old
    assert leftovers(data_dir, master_key_path) == []
    assert readable(data_dir, master_key_path) == ["Fjordlys Energi A/S", "Nordlys IT ApS"]
    assert rotation.resume(data_dir, master_key_path) is None


def test_ting_wont_start_with_a_rotation_unfinished(stocked, engine, data_dir,
                                                      master_key_path, monkeypatch) -> None:
    import subprocess
    import sys

    engine.dispose()

    def power_cut(data_dir, path):
        raise SystemExit("power cut")

    monkeypatch.setattr(rotation, "_finish", power_cut)
    with pytest.raises(SystemExit):
        rotation.rotate(data_dir, master_key_path)
    env = {"PATH": "/usr/local/bin:/usr/bin:/bin", "TING_DATA_DIR": str(data_dir),
           "TING_MASTER_KEY_PATH": str(master_key_path)}
    for module in ("app.migrate", "app.worker"):
        started = subprocess.run([sys.executable, "-m", module], capture_output=True, text=True,
                                 timeout=60, env=env)
        assert started.returncode == 1, module
        assert "ting keys rotate" in started.stdout + started.stderr, module


def test_a_master_key_that_doesnt_open_the_data_is_refused(stocked, engine, data_dir,
                                                           master_key_path) -> None:
    engine.dispose()
    master_key_path.write_bytes(bytes(32))
    with pytest.raises(RotationError, match="doesn't open this data"):
        rotation.rotate(data_dir, master_key_path)
    assert not rotation.pending(master_key_path)


def test_a_copy_made_under_an_older_key_moves_to_the_current_one(stocked, engine, data_dir,
                                                                 master_key_path,
                                                                 tmp_path) -> None:
    import shutil

    engine.dispose()
    copy = tmp_path / "copy"
    shutil.copytree(data_dir, copy)
    old = master_key_path.read_bytes()
    rotation.rotate(data_dir, master_key_path)
    assert not rotation.opens(copy, master_key_path.read_bytes())

    assert rotation.rewrap_restored(copy, old, master_key_path) == 2
    assert readable(copy, master_key_path) == ["Fjordlys Energi A/S", "Nordlys IT ApS"]
