"""A customer's agreements

Revision ID: 0022
Revises: 0021

What was signed and what it covers: versions, term and sections are sealed with
the customer's key; the status and the dates that drive warnings (start, end,
the last day to give notice, whether it renews by itself) stay plain.
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "customer_agreements",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("starts_on", sa.Date(), nullable=True),
        sa.Column("ends_on", sa.Date(), nullable=True),
        sa.Column("notice_by", sa.Date(), nullable=True),
        sa.Column("auto_renews", sa.Boolean(), nullable=False),
        sa.Column("sealed", sa.LargeBinary(), nullable=False),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sqlite_autoincrement=True,
    )
    op.create_index("ix_customer_agreements_customer_id", "customer_agreements", ["customer_id"])


def downgrade() -> None:
    op.drop_index("ix_customer_agreements_customer_id", table_name="customer_agreements")
    op.drop_table("customer_agreements")
