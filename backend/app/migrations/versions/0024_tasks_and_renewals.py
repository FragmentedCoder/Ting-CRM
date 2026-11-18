"""Tasks, recurring work and renewals

Revision ID: 0024
Revises: 0023

What a task or renewal says is sealed with the customer's key. Its dates, its
state and who it's for stay plain: My work, warnings and the wall display need
them across customers without opening each one.
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0024"
down_revision: str | None = "0023"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "customer_tasks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("due_on", sa.Date(), nullable=False),
        sa.Column("done_at", sa.DateTime(), nullable=True),
        sa.Column("done_by", sa.Integer(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("audience", sa.String(length=12), nullable=False),
        sa.Column("sealed", sa.LargeBinary(), nullable=False),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["done_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sqlite_autoincrement=True,
    )
    op.create_index("ix_customer_tasks_customer_id", "customer_tasks", ["customer_id"])
    op.create_index("ix_customer_tasks_due_on", "customer_tasks", ["due_on"])
    op.create_table(
        "customer_task_people",
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["task_id"], ["customer_tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("task_id", "user_id"),
    )
    op.create_index("ix_customer_task_people_user_id", "customer_task_people", ["user_id"])
    op.create_table(
        "customer_renewals",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("renews_on", sa.Date(), nullable=False),
        sa.Column("decision", sa.String(length=10), nullable=False),
        sa.Column("warn_days", sa.Integer(), nullable=False),
        sa.Column("audience", sa.String(length=12), nullable=False),
        sa.Column("sealed", sa.LargeBinary(), nullable=False),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sqlite_autoincrement=True,
    )
    op.create_index("ix_customer_renewals_customer_id", "customer_renewals", ["customer_id"])
    op.create_index("ix_customer_renewals_renews_on", "customer_renewals", ["renews_on"])
    op.create_table(
        "customer_renewal_people",
        sa.Column("renewal_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["renewal_id"], ["customer_renewals.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("renewal_id", "user_id"),
    )
    op.create_index("ix_customer_renewal_people_user_id", "customer_renewal_people", ["user_id"])


def downgrade() -> None:
    op.drop_table("customer_renewal_people")
    op.drop_table("customer_renewals")
    op.drop_table("customer_task_people")
    op.drop_table("customer_tasks")
