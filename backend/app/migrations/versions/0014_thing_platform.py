"""Þing's platform: no projects, three roles, plain assignments

Revision ID: 0014
Revises: 0013

Skjald's projects (and their teams, sites, numbers and classification), its
report language per customer and its Manager, Report Designer and Reviewer roles
have no place in Þing. Tables and columns are dropped in place, never rebuilt
(see 0003): with foreign keys on, dropping a rebuilt table's old copy would delete
every row that cascades from it. Someone who held only a removed role keeps their
account with no role; nobody is given more than they had.
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | None = None
depends_on: str | None = None

def upgrade() -> None:
    for table in ("project_members", "project_sites", "projects"):
        op.drop_table(table)
    op.execute("DELETE FROM settings WHERE key LIKE 'project_counter/%'")
    op.execute("DELETE FROM user_roles WHERE role IN ('manager', 'report_designer', 'reviewer')")
    for table, column in (("customers", "language"),
                          ("customer_assignments", "as_technician"),
                          ("customer_assignments", "as_reviewer")):
        op.execute(f"ALTER TABLE {table} DROP COLUMN {column}")


def downgrade() -> None:
    # The structure comes back; projects, removed roles and capacities don't.
    op.execute("ALTER TABLE customers ADD COLUMN language VARCHAR(5) NOT NULL DEFAULT 'da'")
    op.execute("ALTER TABLE customer_assignments ADD COLUMN as_technician BOOLEAN NOT NULL "
               "DEFAULT 1")
    op.execute("ALTER TABLE customer_assignments ADD COLUMN as_reviewer BOOLEAN NOT NULL "
               "DEFAULT 0")
    op.create_table(
        "projects",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("customer_id", sa.Integer(),
                  sa.ForeignKey("customers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("number", sa.String(length=20), nullable=False, unique=True),
        sa.Column("responsible_id", sa.Integer(),
                  sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("contact_id", sa.Integer(),
                  sa.ForeignKey("customer_contacts.id", ondelete="SET NULL"), nullable=True),
        sa.Column("classification", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"),
                  nullable=True),
        sa.Column("archived_at", sa.DateTime(), nullable=True),
        sa.Column("archived_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"),
                  nullable=True),
        sa.Column("sealed", sa.LargeBinary(), nullable=False, server_default=sa.text("x''")),
        sa.Column("reviewer_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"),
                  nullable=True),
        sqlite_autoincrement=True,
    )
    op.create_index("ix_projects_customer_id", "projects", ["customer_id"])
    op.create_table(
        "project_sites",
        sa.Column("project_id", sa.Integer(),
                  sa.ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("site_id", sa.Integer(),
                  sa.ForeignKey("customer_sites.id", ondelete="CASCADE"), primary_key=True),
    )
    op.create_index("ix_project_sites_site_id", "project_sites", ["site_id"])
    op.create_table(
        "project_members",
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="CASCADE"),
                  primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"),
                  primary_key=True),
        sa.Column("added_at", sa.DateTime(), nullable=False),
        sa.Column("added_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"),
                  nullable=True),
        sa.Column("as_role", sa.String(length=20), nullable=False,
                  server_default="technician"),
    )
    op.create_index("ix_project_members_user_id", "project_members", ["user_id"])
