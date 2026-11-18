"""Pinned warnings on a customer

Revision ID: 0018
Revises: 0017

Up to three one-line warnings per customer that every technician sees first,
pinned by a Manager or Administrator. What they say is sealed with the
customer's key; who pinned them and when stay plain.
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "customer_pins",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("sealed", sa.LargeBinary(), nullable=False),
        sa.Column("pinned_by", sa.Integer(), nullable=True),
        sa.Column("pinned_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["pinned_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sqlite_autoincrement=True,
    )
    op.create_index("ix_customer_pins_customer_id", "customer_pins", ["customer_id"])


def downgrade() -> None:
    op.drop_index("ix_customer_pins_customer_id", table_name="customer_pins")
    op.drop_table("customer_pins")
