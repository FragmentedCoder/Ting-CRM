import pytest
from sqlalchemy import select

from app import console, jobs, worker
from app import db as db_module
from app.audit import AuditEntry
from app.crypto import rotation
from app.crypto.key_files import load_or_create_backup_key
from app.crypto.keys import from_kit_text
from app.policy import Setting


@pytest.fixture
def server(engine, monkeypatch):
    """The console reads the app's own engine."""
    monkeypatch.setattr(db_module, "get_engine", lambda: engine)
    return engine


@pytest.fixture
def the_worker(session, monkeypatch, frozen_clock):
    """A worker that has just beaten, and does each job while the console waits."""
    import app.backups  # noqa: F401 - registers the job kinds

    worker.beat(session, frozen_clock.now)
    session.commit()
    monkeypatch.setattr(jobs, "HANDLERS", dict(jobs.HANDLERS))
    monkeypatch.setattr(console.time, "sleep", lambda seconds: jobs.run_one(session))
    return session


def test_status_lists_every_check(server, session, capsys, no_breach_found, data_dir,
                                  master_key_path) -> None:
    load_or_create_backup_key(data_dir, master_key_path)
    code = console.main(["status"])
    out = capsys.readouterr().out
    for label in ("Database", "Audit log", "Keys", "Disk space", "Background worker", "Backups"):
        assert label in out, label
    assert rotation.key_id(master_key_path.read_bytes()) in out
    assert code == 1  # no worker has ever run here: that's a problem


def test_a_backup_from_the_console_waits_for_the_worker(server, the_worker, capsys) -> None:
    jobs.HANDLERS["backup"] = lambda db, job: {"snapshot": "0b37addf", "bytes": 4200,
                                               "added": 1300}
    assert console.main(["backup"]) == 0
    out = capsys.readouterr().out
    assert "Backup 1 to this server: waiting for the worker" in out
    assert "Backup to this server: backed up 4,200 bytes (1,300 new), snapshot 0b37addf." in out
    job = the_worker.scalar(select(jobs.Job))
    assert job.data() == {"target": "local", "via": "console"}
    logged = the_worker.scalar(select(AuditEntry).where(
        AuditEntry.action == "backup.backup_requested"))
    assert logged.actor_name == "console"


def test_a_failed_restore_test_says_why(server, the_worker, capsys) -> None:
    def broken(db, job):
        raise RuntimeError("the disk is full")

    jobs.HANDLERS["restore_test"] = broken
    assert console.main(["restore-test"]) == 1
    err = capsys.readouterr().err
    assert ("Restore test to this server failed: RuntimeError: the disk is full; the worker "
            "tries again") in err


def test_nothing_is_queued_without_a_worker(server, session, capsys) -> None:
    assert console.main(["backup"]) == 1
    assert "The worker isn't running" in capsys.readouterr().err
    assert session.scalar(select(jobs.Job)) is None


def test_the_console_names_the_ting_command_on_the_backups_page(server, the_worker, client,
                                                                 admin) -> None:
    jobs.HANDLERS["backup"] = lambda db, job: {"snapshot": "0b37addf"}
    console.main(["backup"])
    runs = client.get("/api/admin/backups", headers=admin[1]).json()["runs"]
    assert runs[0]["requested_by"] == "The ting command"


def test_rotating_from_the_console_prints_the_new_key_for_the_kit(
    server, session, capsys, data_dir, master_key_path
) -> None:
    load_or_create_backup_key(data_dir, master_key_path)
    old = master_key_path.read_bytes()
    session.close()
    server.dispose()
    assert console.main(["rotate-master-key"]) == 0
    out = capsys.readouterr().out
    new = master_key_path.read_bytes()
    assert f"{rotation.key_id(old)} -> {rotation.key_id(new)}" in out
    kit_line = out.split("for the recovery kit (put it in place of the old one):")[1]
    assert from_kit_text(kit_line.strip().splitlines()[0]) == new
    assert "until the backups made before now have aged out, after 90 days" in out


def test_rotating_waits_for_ting_to_stop(server, session, capsys, frozen_clock,
                                           master_key_path) -> None:
    worker.beat(session, frozen_clock.now)
    session.commit()
    old = master_key_path.read_bytes()
    assert console.main(["rotate-master-key"]) == 1
    assert "stop Þing first" in capsys.readouterr().err
    assert master_key_path.read_bytes() == old


def test_a_worker_that_stopped_cleanly_isnt_running(server, session, capsys, frozen_clock,
                                                   data_dir, master_key_path) -> None:
    """ting keys rotate stops the worker a moment before: its last beat is recent,
    but it said it stopped after it."""
    worker.beat(session, frozen_clock.now)
    frozen_clock.advance(seconds=20)
    session.merge(Setting(key=worker.STOPPED, value=frozen_clock.now.isoformat()))
    session.commit()
    assert not worker.running(session, frozen_clock.now)
    frozen_clock.advance(seconds=20)
    worker.beat(session, frozen_clock.now)  # started again
    assert worker.running(session, frozen_clock.now)
    frozen_clock.advance(minutes=3)
    assert not worker.running(session, frozen_clock.now)  # gone quiet


def test_rotating_finishes_one_left_halfway_first(server, session, capsys, data_dir,
                                                  master_key_path, monkeypatch) -> None:
    load_or_create_backup_key(data_dir, master_key_path)
    session.close()
    server.dispose()
    finish = rotation._finish

    def power_cut(data_dir, path):
        raise SystemExit("power cut")

    monkeypatch.setattr(rotation, "_finish", power_cut)
    with pytest.raises(SystemExit):
        rotation.rotate(data_dir, master_key_path)
    monkeypatch.setattr(rotation, "_finish", finish)
    assert console.main(["rotate-master-key"]) == 0
    assert "A rotation that stopped halfway is finished now." in capsys.readouterr().out
    assert not rotation.pending(master_key_path)


def test_an_unknown_command_shows_what_there_is(capsys) -> None:
    assert console.main(["format-disk"]) == 2
    assert "rotate-master-key" in capsys.readouterr().err


def test_ting_admin_recovery_code_gives_the_break_glass_administrator_a_new_one(
    server, session, make_user, capsys
) -> None:
    from app.auth.mfa import issue_recovery_codes, use_recovery_code

    ingrid = make_user("ingrid", is_break_glass=True)
    (old,) = issue_recovery_codes(session, ingrid.id)
    session.commit()

    assert console.main(["recovery-code"]) == 0
    out = capsys.readouterr().out
    (new,) = [line.strip() for line in out.splitlines() if line.count("-") == 5]
    assert "for the break-glass Administrator, ingrid" in out
    assert "the one before, which no longer does" in out
    assert use_recovery_code(session, ingrid.id, old) is None
    assert use_recovery_code(session, ingrid.id, new) == 1
    logged = session.scalar(select(AuditEntry).where(
        AuditEntry.action == "auth.mfa.recovery_codes_issued"))
    session.commit()
    assert logged.actor_name == "console" and new not in (logged.details or "")


def test_ting_admin_recovery_code_needs_a_break_glass_administrator(server, capsys) -> None:
    assert console.main(["recovery-code"]) == 1
    assert "no break-glass Administrator yet" in capsys.readouterr().err

