import threading
from datetime import timedelta

import pytest
from sqlalchemy.orm import Session

from app import jobs, worker
from app.jobs import Job
from app.migrate import is_current


@pytest.fixture
def handled(monkeypatch):
    """Handlers for the tests' own kinds of job; the registry is restored after."""
    calls: list[int] = []
    monkeypatch.setattr(jobs, "HANDLERS", dict(jobs.HANDLERS))

    @jobs.handles("ok")
    def _ok(db, job):
        calls.append(job.id)
        return {"echo": job.data()}

    @jobs.handles("broken")
    def _broken(db, job):
        raise RuntimeError("the disk is full")

    return calls


def test_a_slot_is_queued_once(session) -> None:
    first = jobs.enqueue(session, "ok", slot="ok/2026-10-24")
    again = jobs.enqueue(session, "ok", slot="ok/2026-10-24")
    session.commit()
    assert again.id == first.id
    assert session.query(Job).count() == 1


def test_jobs_run_in_order_when_due(frozen_clock, session, handled) -> None:
    later = jobs.enqueue(session, "ok", {"n": 2}, run_after=frozen_clock.now + timedelta(hours=1))
    first = jobs.enqueue(session, "ok", {"n": 1})
    session.commit()

    done = jobs.run_one(session)
    assert done is not None and done.id == first.id
    assert (done.state, done.outcome(), done.attempts) == ("done", {"echo": {"n": 1}}, 1)
    assert jobs.run_one(session) is None  # the other isn't due yet
    frozen_clock.advance(hours=1)
    assert jobs.run_one(session).id == later.id
    assert handled == [first.id, later.id]


def test_a_failing_job_is_tried_again_then_given_up(frozen_clock, session, handled) -> None:
    job = jobs.enqueue(session, "broken")
    session.commit()
    jobs.run_one(session)
    assert (job.state, job.attempts) == ("queued", 1)
    assert job.error == "RuntimeError: the disk is full"
    assert job.run_after == frozen_clock.now + timedelta(minutes=5)
    for _ in range(jobs.MAX_ATTEMPTS - 1):
        frozen_clock.advance(minutes=30)
        jobs.run_one(session)
    assert (job.state, job.attempts) == ("failed", jobs.MAX_ATTEMPTS)
    assert job.finished_at is not None


def test_a_job_nothing_handles_fails_at_once(session) -> None:
    job = jobs.enqueue(session, "mystery")
    session.commit()
    jobs.run_one(session)
    assert (job.state, job.attempts) == ("failed", 1)


def test_a_job_left_running_by_a_stopped_worker_is_put_back(frozen_clock, session) -> None:
    job = jobs.enqueue(session, "ok")
    session.commit()
    jobs.claim(session)
    assert jobs.recover_stale(session) == 0
    frozen_clock.advance(hours=3)
    assert jobs.recover_stale(session) == 1
    assert job.state == "queued" and "stopped" in job.error


def test_schedules_queue_each_slot_once(frozen_clock, session, monkeypatch) -> None:
    monkeypatch.setattr(jobs, "SCHEDULES", [
        lambda db, now: [("ok", f"ok/{now.date().isoformat()}", {"day": now.day})],
    ])
    assert jobs.queue_due(session, frozen_clock.now) == 1
    assert jobs.queue_due(session, frozen_clock.now) == 0
    frozen_clock.advance(days=1)
    assert jobs.queue_due(session, frozen_clock.now) == 1


def test_old_finished_jobs_are_forgotten(frozen_clock, session, handled) -> None:
    jobs.enqueue(session, "ok")
    session.commit()
    jobs.run_one(session)
    frozen_clock.advance(days=91)
    jobs.enqueue(session, "ok")
    session.commit()
    jobs.run_one(session)
    assert jobs.prune(session) == 1
    assert session.query(Job).count() == 1


def test_two_workers_never_take_the_same_job(engine) -> None:
    with Session(engine) as db:
        for _ in range(20):
            jobs.enqueue(db, "ok")
        db.commit()
    taken: list[int] = []

    def take() -> None:
        with Session(engine, expire_on_commit=False) as db:
            while (job := jobs.claim(db)) is not None:
                taken.append(job.id)

    workers = [threading.Thread(target=take) for _ in range(4)]
    for thread in workers:
        thread.start()
    for thread in workers:
        thread.join()
    assert sorted(taken) == list(range(1, 21))


def test_the_worker_beats_and_keeps_house(frozen_clock, session) -> None:
    assert worker.last_beat(session) is None
    worker.beat(session, frozen_clock.now)
    assert worker.last_beat(session) == frozen_clock.now
    assert "prune_jobs" in jobs.HANDLERS


def test_the_worker_waits_for_an_up_to_date_schema(engine, data_dir, master_key_path) -> None:
    from app.db import make_engine
    from app.migrate import upgrade

    assert is_current(engine)
    older = make_engine(data_dir.parent / "older", master_key_path)
    upgrade(older, "0011")
    assert not is_current(older)
    older.dispose()


def test_the_worker_runs_jobs_in_a_process_of_its_own(engine, data_dir, master_key_path) -> None:
    """The worker loads no routes, so it must load every table itself: a job links
    to a user, and that link has to resolve there too."""
    import subprocess
    import sys

    script = """
from sqlalchemy.orm import Session
import app.worker
import app.backups
from app import clock, jobs
from app.db import get_engine
with Session(get_engine()) as db:
    jobs.queue_due(db, clock.utcnow())
    print(jobs.run_one(db).state)
"""
    done = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, timeout=120,
        env={"PATH": "/usr/local/bin:/usr/bin:/bin", "TING_DATA_DIR": str(data_dir),
             "TING_MASTER_KEY_PATH": str(master_key_path)})
    assert done.returncode == 0, done.stderr[-2000:]
    assert done.stdout.strip() in {"done", "queued", "failed"}
