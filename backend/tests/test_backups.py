import json
import os
import shutil
import subprocess
from datetime import UTC, datetime

import pytest
import sqlcipher3
from sqlalchemy import select, text

from app import backups, jobs
from app.audit import AuditEntry
from app.backups import BackupError, Plan, Target
from app.crypto.key_files import load_or_create_backup_key, load_or_create_database_key
from app.crypto.keys import from_kit_text, to_kit_text
from app.roles import Role, grant_role
from app.sealed_settings import save_secrets
from tests.conftest import PASSWORD

BACKUPS = "/api/admin/backups"
needs_restic = pytest.mark.skipif(shutil.which("restic") is None, reason="restic isn't installed")


# What a target means


def test_each_kind_of_target_is_a_restic_repository() -> None:
    assert backups.repository(Target()) == "/backups/restic"
    smb = Target(kind="smb", smb_host="nas.local", smb_share="backup", smb_path="/ting/",
                 smb_username="ting")
    assert backups.repository(smb) == "rclone:tingsmb:backup/ting"
    s3 = Target(kind="s3", s3_endpoint="https://s3.example.com/", s3_bucket="vault",
                s3_access_key_id="AKIA")
    assert backups.repository(s3) == "s3:https://s3.example.com/vault/ting"


def test_secrets_go_to_restic_as_environment_never_as_arguments() -> None:
    s3 = Target(kind="s3", s3_endpoint="https://s3.example.com", s3_bucket="vault",
                s3_access_key_id="AKIA", s3_region="eu-north-1")
    env = backups.environment(s3, {"s3_secret_access_key": "s3cret"}, "KEYTEXT")
    assert env["AWS_SECRET_ACCESS_KEY"] == "s3cret" and env["RESTIC_PASSWORD"] == "KEYTEXT"
    assert env["AWS_DEFAULT_REGION"] == "eu-north-1"


def test_the_repository_password_is_the_recovery_kits_backup_key() -> None:
    key = bytes(range(32))
    kit = to_kit_text(key)
    assert " " in kit
    assert backups.password(key) == kit.replace(" ", "")
    assert from_kit_text(backups.password(key)) == key


def test_restic_complaints_are_said_plainly() -> None:
    assert "another key" in backups._explain(12, "Fatal: wrong password or no key found")
    assert backups._explain(1, "dial tcp: lookup nas: no such host") == (
        "The backup target can't be reached.")
    assert "refused" in backups._explain(1, "Access Denied (403)")
    assert backups._explain(1, "Fatal: something odd\n") == "Fatal: something odd"


def test_a_target_says_what_it_still_needs() -> None:
    assert Target().missing() is None
    assert "server" in (Target(kind="smb").missing() or "")
    assert "bucket" in (Target(kind="s3", s3_endpoint="https://s3.example.com").missing() or "")
    with pytest.raises(ValueError):
        Target(kind="smb", smb_share="a share; rm -rf /")


# When


NAS = Target(id="smb", kind="smb", smb_host="nas.local", smb_share="backup",
             smb_username="ting")


def test_the_nightly_backup_is_due_from_its_hour_for_each_target(frozen_clock, session) -> None:
    morning = datetime(2026, 10, 24, 1, 30, tzinfo=UTC)
    assert backups._nightly(session, morning) == []
    late = datetime(2026, 10, 24, 2, 0, tzinfo=UTC)
    assert backups._nightly(session, late) == [
        ("backup", "backup/2026-10-24/local", {"target": "local"})]
    backups.save_plan(session, Plan(targets=[Target(), NAS, Target(id="s3", kind="s3")]))
    assert backups._nightly(session, late) == [  # the S3 target still needs its details
        ("backup", "backup/2026-10-24/local", {"target": "local"}),
        ("backup", "backup/2026-10-24/smb", {"target": "smb"})]
    backups.save_plan(session, Plan(targets=[]))
    assert backups._nightly(session, late) == []


def test_each_target_is_restore_tested_once_it_has_a_backup(frozen_clock, session) -> None:
    backups.save_plan(session, Plan(targets=[Target(), NAS]))
    assert backups._weekly_restore_test(session, frozen_clock.now) == []
    job = jobs.enqueue(session, "backup", {"target": "smb"})
    jobs.finish(session, job, {})
    assert backups._weekly_restore_test(session, frozen_clock.now) == [
        ("restore_test", "restore_test/2026-W43/smb", {"target": "smb"})]


def test_the_next_backup_time() -> None:
    now = datetime(2026, 10, 24, 1, 0, tzinfo=UTC)
    plan = Plan(hour=2)
    assert backups.next_backup(plan, False, now) == datetime(2026, 10, 24, 2, tzinfo=UTC)
    assert backups.next_backup(plan, True, now) == datetime(2026, 10, 25, 2, tzinfo=UTC)
    afternoon = datetime(2026, 10, 24, 15, 0, tzinfo=UTC)
    assert backups.next_backup(plan, False, afternoon) == afternoon  # missed: due now
    assert backups.next_backup(Plan(targets=[]), False, now) is None


def test_a_single_target_saved_before_is_read_as_the_first(session, data_dir) -> None:
    """Saved before there could be several targets: the target, and its secret at the
    top of the sealed secrets."""
    from app.policy import Setting
    from app.sealed_settings import save_secrets

    session.merge(Setting(key=backups.OLD_TARGET_SETTING, value=json.dumps({
        "kind": "smb", "hour": 4, "keep_days": 30, "smb_host": "nas.local",
        "smb_share": "backup", "smb_username": "ting"})))
    save_secrets(session, backups.SECRETS, {"smb_password": "nas-secret"})
    session.commit()
    plan = backups.load_plan(session)
    assert (plan.hour, plan.keep_days, [t.id for t in plan.targets]) == (4, 30, ["smb"])
    assert backups.load_target_secrets(session, plan) == {"smb": {"smb_password": "nas-secret"}}
    session.merge(Setting(key=backups.OLD_TARGET_SETTING, value=json.dumps({"kind": "off"})))
    session.commit()
    assert backups.load_plan(session).targets == []


# Backing up and restoring, with restic itself


@pytest.fixture
def local_repository(tmp_path, monkeypatch, data_dir, engine):
    from app.settings import settings

    monkeypatch.setattr(settings, "data_dir", str(data_dir))
    repo = tmp_path / "repo"
    monkeypatch.setattr(backups, "LOCAL_REPOSITORY", str(repo))
    return repo


def run(session, kind):
    job = jobs.enqueue(session, kind)
    session.commit()
    jobs.run_one(session)
    return job


@needs_restic
def test_a_backup_restores_and_checks_out(local_repository, session, make_user, data_dir,
                                          master_key_path) -> None:
    grant_role(session, make_user(), Role.TECHNICIAN, actor=None, ip=None)
    session.commit()

    backup = run(session, "backup")
    assert backup.state == "done", backup.error
    assert backup.outcome()["repository_made"] and backup.outcome()["files"] >= 3
    tested = run(session, "restore_test")
    assert tested.state == "done", tested.error
    assert tested.outcome()["audit_entries"] >= 1
    actions = list(session.scalars(select(AuditEntry.action).where(
        AuditEntry.action.like("backup.%"))))
    assert actions == ["backup.completed", "backup.restore_tested"]

    # The recovery kit's backup key, as written there, opens the repository.
    kit = to_kit_text(load_or_create_backup_key(data_dir, master_key_path))
    listed = subprocess.run(
        ["restic", "snapshots", "--json"], capture_output=True, text=True, check=True,
        env={"RESTIC_REPOSITORY": str(local_repository), "PATH": os.environ["PATH"],
             "RESTIC_PASSWORD": kit.replace(" ", "")})
    assert len(json.loads(listed.stdout)) == 1


@needs_restic
def test_a_repository_made_with_another_key_is_refused_plainly(local_repository,
                                                              session) -> None:
    subprocess.run(["restic", "init"], capture_output=True, check=True, env={
        "RESTIC_REPOSITORY": str(local_repository), "RESTIC_PASSWORD": "someone else's",
        "PATH": os.environ["PATH"]})
    backup = run(session, "backup")
    assert backup.state == "queued" and "another key" in backup.error
    failed = session.scalar(select(AuditEntry).where(AuditEntry.action == "backup.failed"))
    assert "another key" in failed.details


def test_a_tampered_copy_fails_the_restore_check(local_repository, session, data_dir,
                                                 master_key_path, tmp_path) -> None:
    from app import audit

    audit.append(session, "test.entry", details={"n": 1})
    session.commit()
    folder = tmp_path / "copy"
    schema = session.execute(text("SELECT version_num FROM alembic_version")).scalar()
    backups._stage(folder, {"schema": schema, "audit_entries": 1})
    assert backups.check_restored(folder)["audit_entries"] == 1

    key = load_or_create_database_key(data_dir, master_key_path)
    copy = sqlcipher3.connect(str(folder / "ting.db"))
    copy.execute(f"PRAGMA key = \"x'{key.hex()}'\"")
    # Someone with the file and the key can drop the triggers that keep the log
    # append-only; the hash chain still shows the change.
    for (name,) in copy.execute(
            "SELECT name FROM sqlite_master WHERE type = 'trigger' AND tbl_name = 'audit_log'"
    ).fetchall():
        copy.execute(f"DROP TRIGGER {name}")
    copy.execute("UPDATE audit_log SET details = '{\"n\":2}'")
    copy.commit()
    copy.close()
    with pytest.raises(BackupError, match="audit log breaks"):
        backups.check_restored(folder)


# The admin panel


@pytest.fixture
def as_admin(admin):
    return admin[1]


S3 = {"kind": "s3", "s3_endpoint": "https://s3.example.com", "s3_bucket": "vault",
      "s3_access_key_id": "AKIA", "s3_secret_access_key": "s3cret"}


def test_the_status_tells_where_when_and_how_it_went(client, as_admin) -> None:
    status = client.get(BACKUPS, headers=as_admin).json()
    [local] = status["targets"]
    assert local["target"]["kind"] == "local" and local["repository"] == "/backups/restic"
    assert local["words"] == "this server" and local["last_backup"] is None
    assert status["runs"] == [] and status["next_backup_at"] is not None


def test_changing_where_backups_go_needs_a_fresh_confirmation(client, as_admin,
                                                              session) -> None:
    both = {"hour": 3, "targets": [{"id": "local", "kind": "local"}, S3]}
    refused = client.put(BACKUPS, headers=as_admin, json=both)
    assert refused.headers["X-Ting-Reason"] == "step_up_required"
    assert "where backups go" in refused.json()["detail"]
    client.post("/api/auth/confirm-password", headers=as_admin, json={"password": PASSWORD})
    saved = client.put(BACKUPS, headers=as_admin, json=both)
    assert saved.status_code == 200, saved.text
    local, s3 = saved.json()["targets"]
    assert (local["target"]["id"], s3["target"]["id"]) == ("local", "s3")
    assert s3["secret_set"] and "s3cret" not in saved.text
    assert s3["repository"] == "s3:https://s3.example.com/vault/ting"
    # The hour alone changes without asking again, and the secret is kept.
    later = client.put(BACKUPS, headers=as_admin, json={"hour": 4, "targets": [
        {"id": "local", "kind": "local"}, {**S3, "id": "s3", "s3_secret_access_key": None}]})
    assert later.status_code == 200 and later.json()["targets"][1]["secret_set"]
    # Removing a target is a change to where backups go.
    removed = client.put(BACKUPS, headers=as_admin, json={"hour": 4, "targets": [
        {"id": "local", "kind": "local"}]})
    assert removed.headers["X-Ting-Reason"] == "step_up_required"
    logged = session.scalars(select(AuditEntry.details).where(
        AuditEntry.action == "backup.settings_changed")).all()
    assert logged == ['{"hour":3,"keep_days":90,"targets":["local","s3"]}',
                      '{"hour":4,"keep_days":90,"targets":["local","s3"]}']
    assert all("s3cret" not in d for d in logged)


def test_each_target_keeps_its_own_secret(client, as_admin, session) -> None:
    client.post("/api/auth/confirm-password", headers=as_admin, json={"password": PASSWORD})
    two = {"targets": [S3, {**S3, "s3_bucket": "vault-2", "s3_secret_access_key": "other"}]}
    saved = client.put(BACKUPS, headers=as_admin, json=two).json()
    assert [t["target"]["id"] for t in saved["targets"]] == ["s3", "s3-2"]
    plan = backups.load_plan(session)
    secrets = backups.load_target_secrets(session, plan)
    session.commit()
    assert secrets == {"s3": {"s3_secret_access_key": "s3cret"},
                       "s3-2": {"s3_secret_access_key": "other"}}


def test_a_new_target_never_takes_a_removed_ones_secret(client, as_admin, session) -> None:
    """A second bucket added after the first was removed gets the ID "s3" again: it
    must not quietly use the old bucket's secret key."""
    client.post("/api/auth/confirm-password", headers=as_admin, json={"password": PASSWORD})
    client.put(BACKUPS, headers=as_admin, json={"targets": [S3]})
    client.post("/api/auth/confirm-password", headers=as_admin, json={"password": PASSWORD})
    other_bucket = {**S3, "s3_bucket": "vault-2", "s3_secret_access_key": None}
    refused = client.put(BACKUPS, headers=as_admin, json={"targets": [other_bucket]})
    assert refused.status_code == 400 and "secret key" in refused.json()["detail"]


def test_a_job_from_before_several_targets_counts_for_the_first_only(session) -> None:
    old = jobs.enqueue(session, "backup")  # no target named: there was only one
    jobs.finish(session, old, {})
    assert backups.latest(session, "backup", Target(), True, "done") is old
    assert backups.latest(session, "backup", NAS, False, "done") is None


@pytest.mark.parametrize(("targets", "said"), [
    ([{"kind": "smb", "smb_host": "nas"}], "share name"),
    ([{"kind": "smb", "smb_host": "nas", "smb_share": "b", "smb_username": "u"}], "password"),
    ([{"kind": "local"}, {"kind": "local"}], "This server can be a target once"),
    ([{"id": "a", "kind": "local"}, {**S3, "id": "a"}], "the same ID"),
])
def test_a_plan_that_wont_do_is_refused(client, as_admin, targets, said) -> None:
    client.post("/api/auth/confirm-password", headers=as_admin, json={"password": PASSWORD})
    refused = client.put(BACKUPS, headers=as_admin, json={"targets": targets})
    assert refused.status_code == 400 and said in refused.json()["detail"]


def test_running_now_queues_one_job_per_target_at_a_time(client, as_admin, session) -> None:
    backups.save_plan(session, Plan(targets=[Target(), NAS]))
    save_secrets(session, backups.SECRETS, {"smb": {"smb_password": "x"}})
    session.commit()
    first = client.post(f"{BACKUPS}/run/backup", headers=as_admin).json()
    assert [(run["target"], run["state"]) for run in first] == [
        ("local", "queued"), ("smb", "queued")]
    again = client.post(f"{BACKUPS}/run/backup?target=smb", headers=as_admin).json()
    assert [run["id"] for run in again] == [first[1]["id"]]
    assert client.get(f"{BACKUPS}/runs/{first[0]['id']}",
                      headers=as_admin).json()["kind"] == "backup"
    assert client.post(f"{BACKUPS}/run/backup?target=nope", headers=as_admin).status_code == 404
    assert client.post(f"{BACKUPS}/run/format_disk", headers=as_admin).status_code == 422


def test_only_administrators_reach_backups(client, make_user, session, full_session) -> None:
    technician = make_user("tor")
    grant_role(session, technician, Role.TECHNICIAN, actor=None, ip=None)
    session.commit()
    assert client.get(BACKUPS, headers=full_session(technician)).status_code == 403


@needs_restic
def test_a_restore_puts_the_backup_back_and_keeps_what_was_there(
    local_repository, session, engine, make_user, data_dir, master_key_path
) -> None:
    from pathlib import Path

    from sqlalchemy.orm import Session

    from app.db import make_engine
    from app.restore import restore
    from app.users import User

    make_user("before")
    assert run(session, "backup").state == "done"
    make_user("after")
    session.commit()
    session.close()
    engine.dispose()  # Þing is stopped

    key_text = backups.password(load_or_create_backup_key(data_dir, master_key_path))
    found = restore(backups.environment(Target(), {}, key_text), "latest", data_dir)
    assert Path(found["kept"], "ting.db").exists()
    restored = make_engine(data_dir, master_key_path)
    with Session(restored) as db:
        usernames = set(db.scalars(select(User.username)))
        # The copy was made while its own backup job ran; nothing runs it now.
        own = db.scalar(select(jobs.Job).where(jobs.Job.kind == "backup"))
    restored.dispose()
    assert "before" in usernames and "after" not in usernames
    assert own.state == "failed" and "the restore ended it" in own.error


@needs_restic
def test_a_restore_keeps_recovery_codes_as_they_are_now_and_is_recorded(
    local_repository, session, engine, make_user, data_dir, master_key_path, monkeypatch
) -> None:
    """A code used since the backup stays used, someone's codes made since stay theirs,
    and the restore is in the restored audit log and mailed to the Administrators."""
    from sqlalchemy.orm import Session

    from app import mail
    from app.audit import AuditEntry, verify
    from app.auth.mfa import issue_recovery_codes, use_recovery_code
    from app.db import make_engine
    from app.restore import restore

    ingrid = make_user("ingrid", email="ingrid@nordlys.example")
    grant_role(session, ingrid, Role.ADMINISTRATOR, actor=None, ip=None)
    bodil = make_user("bodil")
    ingrids = issue_recovery_codes(session, ingrid.id)
    issue_recovery_codes(session, bodil.id)
    mail.save_server(session, mail.MailServer(host="smtp.nordlys.example",
                                              from_address="ting@nordlys.example"))
    session.commit()
    assert run(session, "backup").state == "done"
    # Since the backup: Ingrid used a code, Bodil made new ones.
    assert use_recovery_code(session, ingrid.id, ingrids[0]) is not None
    bodils_new = issue_recovery_codes(session, bodil.id)
    session.commit()
    session.close()
    engine.dispose()  # Þing is stopped

    key_text = backups.password(load_or_create_backup_key(data_dir, master_key_path))
    found = restore(backups.environment(Target(), {}, key_text), "latest", data_dir)
    assert found["recovery_codes"] == "carried_over"
    assert found["recovery_codes_changed_for"] == 2
    restored = make_engine(data_dir, master_key_path)
    with Session(restored) as db:
        assert use_recovery_code(db, ingrid.id, ingrids[0]) is None  # still used
        assert use_recovery_code(db, bodil.id, bodils_new[0]) is not None  # the new set
        logged = db.scalar(select(AuditEntry).where(AuditEntry.action == "backup.restored"))
        assert logged.actor_name == "console" and found["snapshot"] in logged.details
        assert '"recovery_codes":"carried_over"' in logged.details
        assert verify(db).ok
        [notice] = [j.data() for j in db.scalars(select(jobs.Job).where(jobs.Job.kind == "mail"))]
        assert notice["subject"] == "Þing was restored from a backup"
        assert notice["to"] == ["ingrid@nordlys.example"]
        assert "used ones stay used" in notice["body"]
        db.rollback()
    restored.dispose()


@needs_restic
def test_recovery_codes_go_only_to_the_same_person(
    local_repository, session, engine, make_user, data_dir, master_key_path
) -> None:
    """A backup from another server can have someone else under the same ID: their
    codes aren't carried over to them."""
    from sqlalchemy import text
    from sqlalchemy.orm import Session

    from app.auth.mfa import issue_recovery_codes, use_recovery_code
    from app.db import make_engine
    from app.restore import restore

    bodil = make_user("bodil")
    backed_up = issue_recovery_codes(session, bodil.id)
    session.commit()
    assert run(session, "backup").state == "done"
    # Now, here, that ID belongs to someone else, with codes of their own.
    session.execute(text("UPDATE users SET username = 'mette' WHERE id = :id"), {"id": bodil.id})
    issue_recovery_codes(session, bodil.id)
    session.commit()
    session.close()
    engine.dispose()

    key_text = backups.password(load_or_create_backup_key(data_dir, master_key_path))
    found = restore(backups.environment(Target(), {}, key_text), "latest", data_dir)
    assert found["recovery_codes_changed_for"] == 0
    restored = make_engine(data_dir, master_key_path)
    with Session(restored) as db:
        assert use_recovery_code(db, bodil.id, backed_up[0]) is not None  # Bodil's own
        db.rollback()
    restored.dispose()


@needs_restic
def test_a_restore_without_readable_data_says_codes_are_as_backed_up(
    local_repository, session, engine, make_user, data_dir, master_key_path, capsys,
    monkeypatch
) -> None:
    """After losing the server, there's nothing to carry over: say what that means."""
    from app import restore as restore_module

    make_user("ingrid")
    assert run(session, "backup").state == "done"
    session.close()
    engine.dispose()
    (data_dir / "ting.db").write_bytes(b"not a database")  # the disk went
    key_text = backups.password(load_or_create_backup_key(data_dir, master_key_path))
    monkeypatch.setattr(restore_module, "_target_environment",
                        lambda key, repository, target: backups.environment(Target(), {},
                                                                            key_text))
    monkeypatch.setattr("getpass.getpass", lambda prompt="": to_kit_text(
        load_or_create_backup_key(data_dir, master_key_path)))
    assert restore_module.main(["--yes"]) == 0
    out = capsys.readouterr().out
    assert "Recovery codes are as they were at the backup" in out
    assert "any code used since works again" in out


@needs_restic
def test_a_backup_from_before_a_rotation_restores_with_its_master_key(
    local_repository, session, engine, make_user, data_dir, master_key_path
) -> None:
    from sqlalchemy.orm import Session

    from app.crypto import rotation
    from app.db import make_engine
    from app.restore import restore
    from app.users import User

    make_user("before")
    old = master_key_path.read_bytes()
    backup = run(session, "backup")
    assert backup.state == "done", backup.error
    session.close()
    engine.dispose()
    rotated = rotation.rotate(data_dir, master_key_path)

    # The weekly test can't ask for the old key: it says why it can't check this one.
    with Session(make_engine(data_dir, master_key_path)) as db:
        tested = run(db, "restore_test")
        assert tested.state == "queued"
        assert f"made under master key {rotation.key_id(old)}" in tested.error
        assert rotated.new_id in tested.error

    key_text = backups.password(load_or_create_backup_key(data_dir, master_key_path))
    env = backups.environment(Target(), {}, key_text)
    asked: list[str | None] = []

    def wrong(made_under):
        asked.append(made_under)
        return bytes(32)

    with pytest.raises(BackupError, match="doesn't open this backup either"):
        restore(env, "latest", data_dir, older_key=wrong)
    assert asked == [rotation.key_id(old)]

    found = restore(env, "latest", data_dir, older_key=lambda made_under: old)
    assert found["audit_entries"] >= 1
    restored = make_engine(data_dir, master_key_path)  # the server's current master key
    with Session(restored) as db:
        assert "before" in set(db.scalars(select(User.username)))
        moved = db.scalar(select(AuditEntry).where(
            AuditEntry.action == "keys.restored_under_current_master_key"))
        assert moved is not None and rotated.new_id in moved.details
    restored.dispose()


def test_a_damaged_copy_fails_the_integrity_check(local_repository, session, tmp_path) -> None:
    from app import audit

    for n in range(200):  # enough pages that the last isn't the schema's
        audit.append(session, "test.entry", details={"n": n, "pad": "x" * 200})
    session.commit()
    folder = tmp_path / "copy"
    schema = session.execute(text("SELECT version_num FROM alembic_version")).scalar()
    backups._stage(folder, {"schema": schema, "audit_entries": 200})
    database = folder / "ting.db"
    data = bytearray(database.read_bytes())
    data[-2000:-1000] = bytes(1000)  # a page near the end, zeroed
    database.write_bytes(bytes(data))
    with pytest.raises(BackupError, match="integrity check"):
        backups.check_restored(folder)


# Server health, across targets


def test_server_health_reports_every_target(frozen_clock, session) -> None:
    from app.maintenance import _run_backups, _run_restore_test

    backups.save_plan(session, Plan(targets=[Target(), NAS]))
    session.commit()

    def finished(kind, target, state="done", error=None):
        job = jobs.enqueue(session, kind, {"target": target})
        if state == "done":
            jobs.finish(session, job, {"snapshot": "0b37addf"})
        else:
            job.attempts = jobs.MAX_ATTEMPTS
            jobs.fail(session, job, error or "unreachable")
        return job

    assert _run_backups(session).detail == ("No backup to this server yet. No backup to the "
                                            "SMB share \\\\nas.local\\backup yet.")
    finished("backup", "local")
    finished("backup", "smb", "failed", "The backup target can't be reached.")
    check = _run_backups(session)
    assert check.status == "problem"
    assert "Backed up less than an hour ago to this server." in check.detail
    assert "The last backup to the SMB share \\\\nas.local\\backup failed" in check.detail
    finished("backup", "smb")
    assert _run_backups(session).status == "ok"  # a copy away from this server

    assert _run_restore_test(session).status == "warning"  # neither tested yet
    finished("restore_test", "local")
    assert _run_restore_test(session).status == "warning"  # the share not yet
    finished("restore_test", "smb")
    assert _run_restore_test(session).status == "ok"
    finished("restore_test", "smb", "failed")
    assert _run_restore_test(session).status == "problem"
