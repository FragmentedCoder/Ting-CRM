"""Standard services, and each customer's own copies of them

Revision ID: 0021
Revises: 0020

The catalog (standard_services) is the company's own: not sealed. It starts with
the team's list, each with the details worth recording, for Managers to change.
A customer's services (customer_services) are sealed with the customer's key,
except which standard each came from, whether it's active, and its dates.
"""

import json
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | None = None
depends_on: str | None = None


def _d(label: str, key: str, kind: str = "text", choices: list[str] | None = None,
       help: str = "") -> dict[str, object]:
    return {"key": key, "label": label, "kind": kind, "choices": choices or [], "help": help}


# The team's list (docs/architecture.md, data model), in the order the catalog shows it.
STARTERS: list[tuple[str | None, str, str, list[dict[str, object]]]] = [
    ("support", "Support", "When the customer can call us, and on what terms.", [
        _d("When it applies", "when", "choice",
           ["Working hours", "Any time (fixed price)", "None: each job its own case"]),
        _d("Hours", "hours", help="Such as “Monday to Friday, 08:00 to 16:00”."),
        _d("Response times", "response", help="Or the standard SLA."),
    ]),
    ("m365", "Microsoft 365 management", "The customer's Microsoft 365 tenant.", [
        _d("Tenant", "tenant", help="Such as nordlys.onmicrosoft.com."),
        _d("Users", "users", "number"),
        _d("Licences", "licences"),
        _d("We handle", "we_handle"),
    ]),
    ("backup", "Backup", "What's backed up, where the copies go, and how long they're kept.", [
        _d("Product", "product", help="Such as Veeam Backup and Replication."),
        _d("What is backed up", "what"),
        _d("Local copy", "local_copy", help="Where, how long, encrypted or not."),
        _d("Offsite copy", "offsite_copy", help="Where, how long, immutable or not."),
        _d("We handle", "we_handle"),
        _d("Restore test", "restore_test", help="How often, such as every 6 months."),
    ]),
    ("servers", "Servers", "The customer's servers and what we look after on them.", [
        _d("What we look after", "scope"),
    ]),
    ("updates", "Updates and maintenance", "Keeping systems updated, and when.", [
        _d("Rhythm", "rhythm", help="Such as every 3 months."),
        _d("Window", "window", help="When updates may run, such as after 17:00."),
        _d("Special steps", "special", help="Such as also updating a service on the app server."),
    ]),
    ("networking", "Networking", "The customer's network.", [_d("What we look after", "scope")]),
    ("switches", "Switches", "Switches we manage.", [_d("What we look after", "scope")]),
    ("firewall", "Firewall management", "The customer's firewalls.", [
        _d("Model", "model"),
        _d("Failover", "failover"),
        _d("Feature key renews", "feature_key", "date"),
    ]),
    ("printers", "Printers", "Printers we look after.", [_d("What we look after", "scope")]),
    ("hardware", "Hardware", "Hardware bought through us.", [_d("What", "what")]),
    ("licensing", "Licensing", "Licences we buy and renew for the customer.", [
        _d("What", "what"),
    ]),
    ("vulnerability_scanning", "Vulnerability scanning", "Scanning the customer's systems.", [
        _d("Scope", "scope"),
        _d("How often", "rhythm"),
    ]),
]


def upgrade() -> None:
    standard = op.create_table(
        "standard_services",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(length=40), nullable=True),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=False),
        sa.Column("details", sa.Text(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key"),
        sa.UniqueConstraint("name"),
        sqlite_autoincrement=True,
    )
    op.create_table(
        "customer_services",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("standard_service_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("started_on", sa.Date(), nullable=True),
        sa.Column("ended_on", sa.Date(), nullable=True),
        sa.Column("sealed", sa.LargeBinary(), nullable=False),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["standard_service_id"], ["standard_services.id"],
                                ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sqlite_autoincrement=True,
    )
    op.create_index("ix_customer_services_customer_id", "customer_services", ["customer_id"])
    now = datetime.now(UTC).replace(tzinfo=None)
    op.bulk_insert(standard, [
        {"key": key, "name": name, "description": description, "details": json.dumps(details),
         "position": n, "created_at": now}
        for n, (key, name, description, details) in enumerate(STARTERS, start=1)
    ])


def downgrade() -> None:
    op.drop_index("ix_customer_services_customer_id", table_name="customer_services")
    op.drop_table("customer_services")
    op.drop_table("standard_services")
