"""Þing's tag line where Skjald's was saved

Revision ID: 0015
Revises: 0014

Saving Branding stores the tag line with the rest, and on an install set up from
an early build the form held Skjald's own, "Reports worth keeping.". Where that
exact text is stored, it becomes Þing's; any tag line someone chose stays.
"""

import json

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | None = None
depends_on: str | None = None

SKJALD_TAGLINE = "Reports worth keeping."
THING_TAGLINE = "Gather. Agree. Remember."


def upgrade() -> None:
    conn = op.get_bind()
    stored = conn.execute(sa.text("SELECT value FROM settings WHERE key = 'branding'")).scalar()
    if stored is None:
        return
    branding = json.loads(stored)
    if branding.get("tagline") == SKJALD_TAGLINE:
        branding["tagline"] = THING_TAGLINE
        conn.execute(sa.text("UPDATE settings SET value = :value WHERE key = 'branding'"),
                     {"value": json.dumps(branding)})


def downgrade() -> None:
    # Nothing to undo: Þing's tag line is right for every version of Þing.
    pass
