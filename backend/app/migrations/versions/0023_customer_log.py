"""The work log

Revision ID: 0023
Revises: 0022

What was done for a customer, in plain text. The text and everything about an
entry are sealed with the customer's key; when it happened and who wrote it
stay plain, for ordering and the timeline.
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "customer_log",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("happened_at", sa.DateTime(), nullable=False),
        sa.Column("author_id", sa.Integer(), nullable=True),
        sa.Column("sealed", sa.LargeBinary(), nullable=False),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["author_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sqlite_autoincrement=True,
    )
    op.create_index("ix_customer_log_customer_when", "customer_log",
                    ["customer_id", "happened_at"])


def downgrade() -> None:
    op.drop_index("ix_customer_log_customer_when", table_name="customer_log")
    op.drop_table("customer_log")
