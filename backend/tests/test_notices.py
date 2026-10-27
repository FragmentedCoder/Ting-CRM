import json
from pathlib import Path

import pytest
from sqlalchemy import select

from app import backups, jobs, mail, notices
from app.backups import BackupError
from app.crypto.key_files import load_or_create_backup_key
from app.mail import MailServer
from app.roles import Role, grant_role
from app.sealed_settings import save_secrets
from tests.conftest import PASSWORD
from tests.test_mail import SERVER, smtp  # noqa: F401 - the fake mail server

SIGN_IN = "/api/auth/sign-in"


@pytest.fixture
def mail_set_up(session):
    mail.save_server(session, MailServer(**SERVER))
    save_secrets(session, mail.SECRETS, {"password": "mail-secret"})
    session.commit()


@pytest.fixture
def administrators(session, make_user):
    """Two Administrators with an email address, one without, one disabled, and a
    Manager: only the first two get notices."""
    people = {}
    for username, role, email, active in (
        ("ingrid", Role.ADMINISTRATOR, "ingrid@nordlys.example", True),
        ("bodil", Role.ADMINISTRATOR, "bodil@nordlys.example", True),
        ("nomail", Role.ADMINISTRATOR, None, True),
        ("gone", Role.ADMINISTRATOR, "gone@nordlys.example", False),
        ("mona", Role.MANAGER, "mona@nordlys.example", True),
    ):
        user = make_user(username, email=email)
        user.is_active = active
        grant_role(session, user, role, actor=None, ip=None)
        people[username] = user
    session.commit()
    return people


def queued_mail(session) -> list[dict]:
    found = [job.data() for job in
             session.scalars(select(jobs.Job).where(jobs.Job.kind == "mail"))]
    session.commit()
    return found


def test_notices_go_to_active_administrators_with_an_address(session, administrators) -> None:
    assert notices.recipients(session) == ["bodil@nordlys.example", "ingrid@nordlys.example"]


def test_without_email_set_up_nothing_is_queued(session, administrators) -> None:
    assert notices.notify_administrators(session, "Hello", "Body") is None
    assert queued_mail(session) == []


def test_a_notice_is_sent_to_each_once_even_if_sending_fails_halfway(
    session, administrators, mail_set_up, smtp  # noqa: F811
) -> None:
    job = notices.notify_administrators(session, "Hello", "Body")
    session.commit()
    sent_to: list[str] = []
    original = smtp.send_message

    def flaky(self, message):
        if message["To"] == "ingrid@nordlys.example" and not sent_to.count("retry"):
            sent_to.append("retry")
            raise TimeoutError
        sent_to.append(message["To"])
        original(self, message)

    smtp.send_message = flaky
    try:
        jobs.run_one(session)
        assert job.state == "queued" and "didn't answer" in job.error
        job.run_after = job.created_at  # due again now
        session.commit()
        jobs.run_one(session)
    finally:
        smtp.send_message = original
    assert job.state == "done", job.error
    assert sent_to == ["bodil@nordlys.example", "retry", "ingrid@nordlys.example"]
    body = smtp.sent[-1]["message"].get_content()
    assert "Body" in body and "Þing, at https://" in body


def test_a_break_glass_sign_in_tells_the_administrators(
    client, session, make_user, administrators, mail_set_up
) -> None:
    keeper = make_user("keeper", is_break_glass=True)
    grant_role(session, keeper, Role.ADMINISTRATOR, actor=None, ip=None)
    session.commit()
    client.post(SIGN_IN, json={"username": "ingrid", "password": PASSWORD})
    assert queued_mail(session) == []  # an ordinary sign-in
    client.cookies.clear()
    signed_in = client.post(SIGN_IN, json={"username": "keeper", "password": PASSWORD})
    assert signed_in.status_code == 200
    [notice] = queued_mail(session)
    assert notice["subject"] == "Break-glass sign-in to Þing: keeper"
    assert "signed in to the break-glass account keeper" in notice["body"]
    assert notice["to"] == ["bodil@nordlys.example", "ingrid@nordlys.example"]


@pytest.fixture
def fake_restic(monkeypatch, data_dir, master_key_path):
    """restic answering as if a backup were there to restore."""
    load_or_create_backup_key(data_dir, master_key_path)

    def restic(env, *args, timeout=0):
        if args[0] == "snapshots":
            return json.dumps([{"short_id": "0b37addf"}])
        if args[0] == "restore":
            target = Path(args[args.index("--target") + 1], "data")
            target.mkdir(parents=True, exist_ok=True)
            (target / "manifest.json").write_text("{}")
        return ""

    monkeypatch.setattr(backups, "restic", restic)
    monkeypatch.setattr(backups, "check_restored", lambda folder: {
        "schema": "0013", "audit_entries": 1234, "made_at": "2026-10-25T18:50:21+00:00"})


def test_each_restore_test_tells_the_administrators(session, administrators, mail_set_up,
                                                    fake_restic) -> None:
    job = jobs.enqueue(session, "restore_test")
    session.commit()
    jobs.run_one(session)
    assert job.state == "done", job.error
    [notice] = queued_mail(session)
    assert notice["subject"] == "Þing's restore test passed"
    assert "(0b37addf, made 2026-10-25T18:50Z)" in notice["body"]
    assert "1,234 audit log entries" in notice["body"]


@pytest.mark.parametrize("kind", ["backup", "restore_test"])
def test_failures_are_told_once_they_keep_failing(session, administrators, mail_set_up,
                                                  monkeypatch, frozen_clock, data_dir,
                                                  master_key_path, kind) -> None:
    load_or_create_backup_key(data_dir, master_key_path)

    def unreachable(env, *args, timeout=0):
        raise BackupError("The backup target can't be reached.")

    monkeypatch.setattr(backups, "restic", unreachable)
    monkeypatch.setattr(backups, "ensure_repository", unreachable)
    job = jobs.enqueue(session, kind)
    session.commit()
    for attempt in range(1, jobs.MAX_ATTEMPTS + 1):
        jobs.run_one(session)
        frozen_clock.advance(hours=1)
        told = queued_mail(session)
        assert len(told) == (1 if attempt == jobs.MAX_ATTEMPTS else 0), attempt
    assert job.state == "failed"
    assert f"failed {jobs.MAX_ATTEMPTS} times in a row" in told[0]["body"]
    assert "can't be reached" in told[0]["body"]
