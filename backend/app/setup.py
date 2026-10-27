"""First-run setup: the one-time setup token, the company name, setup state.

Until setup is complete, the server can be claimed by whoever holds the setup
token, which only someone with access to the VM can read. Run as
`python -m app.setup` (ting setup-token) to print a new token; the container
does it at start.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from typing import Any

from sqlalchemy.orm import Session

from app import clock
from app.audit import timestamp
from app.policy import Setting

SETUP_KEY = "setup"
COMPANY_KEY = "company"
# 32 letters and digits without look-alikes; 24 of them make 120 bits.
TOKEN_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
TOKEN_GROUPS = 6


def _get(db: Session, key: str) -> dict[str, Any]:
    stored = db.get(Setting, key)
    return json.loads(stored.value) if stored else {}


def _put(db: Session, key: str, value: dict[str, Any]) -> None:
    db.merge(Setting(key=key, value=json.dumps(value)))


def _token_hash(token: str) -> str:
    normalized = token.upper().replace("-", "").replace(" ", "")
    return hashlib.sha256(normalized.encode()).hexdigest()


def setup_complete(db: Session) -> bool:
    return bool(_get(db, SETUP_KEY).get("completed_at"))


def setup_completed_at(db: Session) -> str | None:
    completed = _get(db, SETUP_KEY).get("completed_at")
    return str(completed) if completed else None


def mark_security_reviewed(db: Session) -> None:
    state = _get(db, SETUP_KEY)
    state["security_reviewed_at"] = timestamp(clock.utcnow())
    _put(db, SETUP_KEY, state)


def security_reviewed(db: Session) -> bool:
    return bool(_get(db, SETUP_KEY).get("security_reviewed_at"))


def new_setup_token(db: Session) -> str:
    """Replace the setup token with a new one. Only its hash is stored."""
    token = "-".join(
        "".join(secrets.choice(TOKEN_ALPHABET) for _ in range(4)) for _ in range(TOKEN_GROUPS)
    )
    state = _get(db, SETUP_KEY)
    state["token_hash"] = _token_hash(token)
    _put(db, SETUP_KEY, state)
    return token


def setup_token_valid(db: Session, token: str) -> bool:
    expected = _get(db, SETUP_KEY).get("token_hash")
    if not isinstance(expected, str):
        return False
    return hmac.compare_digest(expected, _token_hash(token))


def mark_recovery_kit_shown(db: Session) -> None:
    state = _get(db, SETUP_KEY)
    state.setdefault("recovery_kit_shown_at", timestamp(clock.utcnow()))
    _put(db, SETUP_KEY, state)


def recovery_kit_shown(db: Session) -> bool:
    return bool(_get(db, SETUP_KEY).get("recovery_kit_shown_at"))


def mark_kit_saved(db: Session) -> None:
    state = _get(db, SETUP_KEY)
    state.setdefault("kit_saved_at", timestamp(clock.utcnow()))
    _put(db, SETUP_KEY, state)


def kit_saved(db: Session) -> bool:
    return bool(_get(db, SETUP_KEY).get("kit_saved_at"))


# The steps after the recovery kit, each set up or left for later.
LATER_STEPS = ("backups", "email", "tls")


def mark_step_done(db: Session, step: str) -> None:
    state = _get(db, SETUP_KEY)
    done = set(state.get("steps_done", []))
    done.add(step)
    state["steps_done"] = sorted(done)
    _put(db, SETUP_KEY, state)


def steps_done(db: Session) -> list[str]:
    return [str(step) for step in _get(db, SETUP_KEY).get("steps_done", [])]


def complete_setup(db: Session) -> None:
    """Finish setup for good: the token stops working and the wizard closes."""
    state = _get(db, SETUP_KEY)
    state["completed_at"] = timestamp(clock.utcnow())
    state.pop("token_hash", None)
    _put(db, SETUP_KEY, state)


def company_name(db: Session) -> str | None:
    name = _get(db, COMPANY_KEY).get("name")
    return str(name) if name else None


def set_company_name(db: Session, name: str) -> None:
    company = _get(db, COMPANY_KEY)
    company["name"] = name.strip()
    _put(db, COMPANY_KEY, company)


def main() -> None:
    from app.db import get_engine
    from app.settings import settings

    with Session(get_engine()) as db:
        if setup_complete(db):
            print("Þing is set up; no setup token is needed.", flush=True)
            return
        token = new_setup_token(db)
        db.commit()
    rule = "=" * 72
    print(
        f"{rule}\n"
        f"  Þing needs setting up. Open {settings.address}/setup and enter:\n\n"
        f"      Setup token: {token}\n\n"
        "  It works until setup is finished. Restarting Þing, or running\n"
        "  `sudo ting setup-token`, prints a new one.\n"
        f"{rule}",
        flush=True,
    )


if __name__ == "__main__":
    main()
