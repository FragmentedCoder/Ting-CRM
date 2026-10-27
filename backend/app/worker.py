"""The background worker: `python -m app.worker`, in a container of its own.

Once a minute it says it's alive (a heartbeat Server health reads) and queues
what the schedules say is due, such as the nightly backup; in between it runs
queued jobs one at a time (app/jobs.py). It starts only once the app has brought
the database schema up to date, and stops between jobs when asked to.
"""

from __future__ import annotations

import logging
import signal
import time
from datetime import datetime, timedelta
from types import FrameType

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

# Every table, so links between them resolve in this process too (the API loads
# them through its routes; the worker has none).
import app.models  # noqa: F401
from app import clock, jobs
from app.crypto import rotation
from app.crypto.key_files import keep_backup_key
from app.db import get_engine
from app.migrate import is_current
from app.policy import Setting
from app.settings import settings

log = logging.getLogger("ting.worker")

HEARTBEAT = "worker/heartbeat"
# When it last stopped cleanly (docker compose stop): a beat before that is history.
STOPPED = "worker/stopped"
IDLE_SECONDS = 5
# It beats every minute; quiet for longer than this, it isn't running.
GONE_AFTER = timedelta(minutes=3)


def beat(db: Session, now: datetime) -> None:
    db.merge(Setting(key=HEARTBEAT, value=now.isoformat()))
    db.commit()


def last_beat(db: Session) -> datetime | None:
    value = db.scalar(select(Setting.value).where(Setting.key == HEARTBEAT))
    return datetime.fromisoformat(value) if value else None


def stopped_at(db: Session) -> datetime | None:
    value = db.scalar(select(Setting.value).where(Setting.key == STOPPED))
    return datetime.fromisoformat(value) if value else None


def running(db: Session, now: datetime) -> bool:
    """Whether a worker runs now: it beat lately, and hasn't stopped since."""
    beaten, stopped = last_beat(db), stopped_at(db)
    if beaten is None or now - beaten >= GONE_AFTER:
        return False
    return stopped is None or stopped < beaten


@jobs.scheduled
def _daily_housekeeping(db: Session, now: datetime) -> list[tuple[str, str, dict[str, object]]]:
    return [("prune_jobs", f"prune_jobs/{now.date().isoformat()}", {})]


@jobs.handles("prune_jobs")
def _prune_jobs(db: Session, job: jobs.Job) -> dict[str, object]:
    return {"removed": jobs.prune(db)}


def _keep_backup_key(warned: bool) -> bool:
    """Keep the backup key's spare copy in step; say once if it can't be. Returns
    whether that was said."""
    try:
        if keep_backup_key(settings.data_dir, settings.master_key_path) is not False or warned:
            return warned
    except OSError:
        if warned:
            return True
    log.warning("The backup key's spare copy can't be kept in /etc/ting/keys: run "
                "ting restart on the server, which makes the folder.")
    return True


def main() -> None:
    # Modules whose jobs the worker runs register them when imported.
    import app.audit_stamps  # noqa: F401
    import app.backups  # noqa: F401
    import app.notices  # noqa: F401

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if rotation.pending(settings.master_key_path):
        log.error("A master key rotation didn't finish. Finish it on the server with: "
                  "ting keys rotate")
        raise SystemExit(1)
    engine = get_engine()
    while not is_current(engine):
        log.info("Waiting for the app to bring the database up to date.")
        time.sleep(IDLE_SECONDS)
    sessions = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    stopping = False

    def stop(signum: int, frame: FrameType | None) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    with sessions() as db:
        recovered = jobs.recover_stale(db)
    log.info("Worker started%s.", f"; put back {recovered} stale jobs" if recovered else "")
    beaten: datetime | None = None
    warned = False
    while not stopping:
        now = clock.utcnow()
        with sessions() as db:
            if beaten is None or now - beaten >= timedelta(minutes=1):
                beat(db, now)
                jobs.queue_due(db, now)
                beaten = now
                warned = _keep_backup_key(warned)
            job = jobs.run_one(db)
            if job is not None:
                log.info("Job %s (%s): %s", job.id, job.kind, job.state)
        if job is None:
            for _ in range(IDLE_SECONDS):
                if stopping:
                    break
                time.sleep(1)
    with sessions() as db:
        db.merge(Setting(key=STOPPED, value=clock.utcnow().isoformat()))
        db.commit()
    log.info("Worker stopped.")


if __name__ == "__main__":
    main()
