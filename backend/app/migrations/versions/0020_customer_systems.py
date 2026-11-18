"""The systems at a customer

Revision ID: 0020
Revises: 0019

Servers, virtual machines on their host, network gear, cloud tenants and
printers. What each is and everything about it is sealed with the customer's
key; its host, the day it was retired and its warranty end stay plain, as
warnings and the host tree need them without opening the customer.
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "customer_systems",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("parent_id", sa.Integer(), nullable=True),
        sa.Column("retired_on", sa.Date(), nullable=True),
        sa.Column("warranty_end", sa.Date(), nullable=True),
        sa.Column("sealed", sa.LargeBinary(), nullable=False),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["parent_id"], ["customer_systems.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sqlite_autoincrement=True,
    )
    op.create_index("ix_customer_systems_customer_id", "customer_systems", ["customer_id"])


def downgrade() -> None:
    op.drop_index("ix_customer_systems_customer_id", table_name="customer_systems")
    op.drop_table("customer_systems")
