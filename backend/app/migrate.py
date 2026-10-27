"""Bring the database schema up to date. Runs before the app starts (see the Dockerfile)."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy.engine import Engine

from app.db import get_engine


def _config() -> Config:
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).parent / "migrations"))
    return config


def upgrade(engine: Engine | None = None, revision: str = "head") -> None:
    config = _config()
    with (engine or get_engine()).connect() as conn:
        config.attributes["connection"] = conn
        command.upgrade(config, revision)


def is_current(engine: Engine) -> bool:
    """Whether the database is at the newest migration (the worker waits for it)."""
    head = ScriptDirectory.from_config(_config()).get_current_head()
    with engine.connect() as conn:
        return MigrationContext.configure(conn).get_current_revision() == head


if __name__ == "__main__":
    import sys

    from app.crypto.rotation import pending
    from app.settings import settings

    if pending(settings.master_key_path):
        print("A master key rotation didn't finish. Finish it on the server with: "
              "ting keys rotate", file=sys.stderr, flush=True)
        sys.exit(1)
    upgrade()
