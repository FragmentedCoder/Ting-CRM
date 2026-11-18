"""Every technician sees every customer; customers are active, departing or former

Revision ID: 0017
Revises: 0016

Technicians now see every customer, as whoever answers the phone helps; an
Administrator can limit one to the customers they usually work with
(users.limited_to_assigned). Customers gain a status and its day: the day a
departing customer leaves, or a former one left. Every customer starts active.
"""

from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # Plain ADD COLUMNs keep every row (see 0003).
    op.execute("ALTER TABLE users ADD COLUMN limited_to_assigned BOOLEAN NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE customers ADD COLUMN status VARCHAR(10) NOT NULL DEFAULT 'active'")
    op.execute("ALTER TABLE customers ADD COLUMN status_date DATE")


def downgrade() -> None:
    op.drop_column("customers", "status_date")
    op.drop_column("customers", "status")
    op.drop_column("users", "limited_to_assigned")
