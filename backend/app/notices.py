"""Emails Þing sends Administrators on its own: each break-glass sign-in, each
restore test, and backups that keep failing.

They go to every active Administrator with an email address. Each is queued as a
job, so the worker sends it (and tries again if the mail server is away) and no
request waits on the mail server. Without email set up, nothing is queued; the
audit log and Server health still say what happened.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit, jobs, mail
from app.roles import Role, UserRole
from app.sealed_settings import load_secrets
from app.settings import settings
from app.users import User

SIGN_OFF = "\n\nÞing, at {address}\n"


def recipients(db: Session) -> list[str]:
    """Every active Administrator's email address."""
    found = db.scalars(
        select(User.email).join(UserRole, UserRole.user_id == User.id)
        .where(UserRole.role == Role.ADMINISTRATOR, User.is_active.is_(True),
               User.email.is_not(None), User.email != "")
        .order_by(User.email)
    )
    return sorted({str(address) for address in found})


def notify_administrators(db: Session, subject: str, body: str) -> jobs.Job | None:
    """Queue an email to the Administrators (the caller commits)."""
    if not mail.load_server(db).configured:
        return None
    to = recipients(db)
    if not to:
        return None
    return jobs.enqueue(db, "mail", {"to": to, "subject": subject,
                                     "body": body + SIGN_OFF.format(address=settings.address)})


@jobs.handles("mail")
def send_queued(db: Session, job: jobs.Job) -> dict[str, Any]:
    message = job.data()
    server = mail.load_server(db)
    password = str(load_secrets(db, mail.SECRETS).get("password", ""))
    db.commit()  # the network follows: hold no lock meanwhile
    # Who has it already, so a try after the mail server failed halfway sends no twice.
    sent = set(message.get("sent", []))
    for to in message["to"]:
        if to in sent:
            continue
        mail.send(server, password, to, message["subject"], message["body"])
        sent.add(to)
        job.payload = json.dumps({**message, "sent": sorted(sent)})
        db.commit()
    audit.append(db, "mail.notice_sent", target_type="job", target_id=str(job.id),
                 details={"subject": message["subject"], "to": len(message["to"])})
    db.commit()
    return {"sent": len(message["to"])}
