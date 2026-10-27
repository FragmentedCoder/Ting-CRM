"""A reusable recovery code for the break-glass Administrator

Revision ID: 0016
Revises: 0015

The break-glass Administrator gets one recovery code that works every time,
instead of ten one-time codes (see app/auth/mfa.py). Codes made before keep
working as they were, one time each, until a new one is made in Your account or
with `ting admin recovery-code`.
"""

from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # A plain ADD COLUMN keeps every row (see 0003).
    op.execute("ALTER TABLE recovery_codes ADD COLUMN reusable BOOLEAN NOT NULL DEFAULT 0")


def downgrade() -> None:
    op.drop_column("recovery_codes", "reusable")
