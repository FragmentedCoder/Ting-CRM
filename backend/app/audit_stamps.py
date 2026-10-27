"""Daily RFC 3161 timestamps of the audit log's newest entry.

The hash chain shows an entry changed or taken out of the middle, but whoever
removes the newest entries leaves a valid, shorter chain. So once a day the
worker sends a timestamp authority (TSA) a fingerprint of the newest entry, its
number and hash, and keeps the token the TSA signs: proof, from outside Þing,
that the entry existed at that time. A stamped entry that later goes missing or
changes shows the log was cut short or edited afterwards. Only the fingerprint
leaves the server.
"""

from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from asn1crypto import cms, tsp  # type: ignore[import-untyped]
from pyhanko.sign.timestamps import HTTPTimeStamper, TimeStamper
from pyhanko.sign.validation.generic_cms import validate_tst_signed_data
from pyhanko_certvalidator import ValidationContext
from sqlalchemy import Integer, LargeBinary, String, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from app import audit, clock, jobs
from app.audit import AuditEntry
from app.db import Base, UTCDateTime
from app.policy import Setting

DEFAULT_TSA = "http://timestamp.digicert.com"
TSA_SETTING = "audit/tsa_url"


class AuditStamp(Base):
    __tablename__ = "audit_stamps"
    __table_args__ = {"sqlite_autoincrement": True}

    id: Mapped[int] = mapped_column(primary_key=True)
    # The entry stamped, as it was.
    seq: Mapped[int] = mapped_column(Integer, index=True)
    entry_hash: Mapped[str] = mapped_column(String(64))
    tsa_url: Mapped[str] = mapped_column(String(300))
    # The TSA's signed token (DER), which anyone can check with OpenSSL.
    token: Mapped[bytes] = mapped_column(LargeBinary)
    stamped_at: Mapped[datetime] = mapped_column(UTCDateTime)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)


class StampError(Exception):
    """A timestamp that couldn't be had, or doesn't say what it should."""


@dataclass
class StampCheck:
    ok: bool
    stamps: int
    latest: AuditStamp | None
    problem: str | None = None


def tsa_url(db: Session) -> str:
    return db.scalar(select(Setting.value).where(Setting.key == TSA_SETTING)) or DEFAULT_TSA


def fingerprint(seq: int, entry_hash: str) -> bytes:
    """What's sent to the TSA: a SHA-256 of the entry's number and hash."""
    return hashlib.sha256(f"ting/audit-entry/{seq}/{entry_hash}".encode()).digest()


def stamper(url: str) -> TimeStamper:
    """The TSA client (tests put an in-process one here)."""
    return HTTPTimeStamper(url, timeout=30)


def validation_context() -> ValidationContext | None:
    """Trust for the TSA's certificate (tests put their own root here); None uses the
    system's trusted roots."""
    return None


def _imprint(token: cms.ContentInfo) -> bytes:
    info: tsp.TSTInfo = token["content"]["encap_content_info"]["content"].parsed
    value: bytes = info["message_imprint"]["hashed_message"].native
    return value


def _stamped_at(token: cms.ContentInfo) -> datetime:
    info: tsp.TSTInfo = token["content"]["encap_content_info"]["content"].parsed
    moment: datetime = info["gen_time"].native
    return moment


async def _ask(url: str, digest: bytes) -> tuple[cms.ContentInfo, bool]:
    token = await stamper(url).async_timestamp(digest, "sha256")
    status = await validate_tst_signed_data(
        token["content"], validation_context(), expected_tst_imprint=lambda _: digest)
    # pyHanko answers with the fields of its signature status, as a dict.
    if not (status.get("intact") and status.get("valid")):
        raise StampError("The timestamp authority's signature doesn't check out.")
    # Trusted: its certificate leads to a root this server trusts.
    return token, status.get("trust_problem_indic") is None


def stamp(db: Session) -> tuple[AuditStamp, bool] | None:
    """Stamp the newest entry. Returns the stamp and whether the TSA's certificate is
    trusted here, or None while the log is empty."""
    head = db.execute(select(AuditEntry.seq, AuditEntry.hash)
                      .order_by(AuditEntry.seq.desc()).limit(1)).first()
    if head is None:
        return None
    url = tsa_url(db)
    db.commit()  # the network call follows: hold no lock meanwhile
    digest = fingerprint(head.seq, head.hash)
    try:
        token, trusted = asyncio.run(_ask(url, digest))
    except StampError:
        raise
    except Exception as exc:  # noqa: BLE001 - network, TSA refusals, odd answers
        raise StampError(f"The timestamp authority at {url} didn't answer usefully: "
                         f"{type(exc).__name__}.") from exc
    if _imprint(token) != digest:
        raise StampError("The timestamp doesn't cover the entry that was sent.")
    record = AuditStamp(seq=head.seq, entry_hash=head.hash, tsa_url=url, token=token.dump(),
                        stamped_at=_stamped_at(token), created_at=clock.utcnow())
    db.add(record)
    db.flush()
    return record, trusted


def check(db: Session) -> StampCheck:
    """Every stamped entry must still be in the log, unchanged, and every token must
    cover what it says it does."""
    stamps = list(db.scalars(select(AuditStamp).order_by(AuditStamp.id)))
    for item in stamps:
        entry = db.get(AuditEntry, item.seq)
        when = item.stamped_at.strftime("%Y-%m-%dT%H:%M:%SZ")
        if entry is None:
            return StampCheck(False, len(stamps), stamps[-1], (
                f"Entry {item.seq}, timestamped {when}, is gone: the log was cut short."))
        if entry.hash != item.entry_hash:
            return StampCheck(False, len(stamps), stamps[-1], (
                f"Entry {item.seq}, timestamped {when}, has changed."))
        if _imprint(cms.ContentInfo.load(item.token)) != fingerprint(item.seq, item.entry_hash):
            return StampCheck(False, len(stamps), stamps[-1], (
                f"The timestamp of entry {item.seq} doesn't match it."))
    return StampCheck(True, len(stamps), stamps[-1] if stamps else None)


@jobs.scheduled
def _daily(db: Session, now: datetime) -> list[tuple[str, str, dict[str, Any]]]:
    # Not while the log is empty (a fresh install), or the day's stamp would be spent.
    if db.scalar(select(AuditEntry.seq).limit(1)) is None:
        return []
    return [("audit_stamp", f"audit_stamp/{now.date().isoformat()}", {})]


@jobs.handles("audit_stamp")
def run_stamp(db: Session, job: jobs.Job) -> dict[str, Any]:
    try:
        stamped = stamp(db)
    except StampError as exc:
        audit.append(db, "audit.stamp_failed", actor_id=job.requested_by, target_type="job",
                     target_id=str(job.id), details={"error": str(exc)[:300]})
        db.commit()
        raise
    if stamped is None:
        return {"skipped": "The log is empty."}
    record, trusted = stamped
    result = {"seq": record.seq, "stamped_at": record.stamped_at.isoformat(),
              "tsa": record.tsa_url, "trusted": trusted}
    audit.append(db, "audit.stamped", actor_id=job.requested_by, target_type="job",
                 target_id=str(job.id), details=result)
    db.commit()
    return result
