"""The other companies in a group that is one customer

Revision ID: 0019
Revises: 0018

A group with subsidiaries is one customer: its own name, CVR number and address
are the main company, and each other company has its name, CVR number and
address here, sealed with the customer's key.
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "customer_companies",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("sealed", sa.LargeBinary(), nullable=False),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sqlite_autoincrement=True,
    )
    op.create_index("ix_customer_companies_customer_id", "customer_companies", ["customer_id"])


def downgrade() -> None:
    op.drop_index("ix_customer_companies_customer_id", table_name="customer_companies")
    op.drop_table("customer_companies")
