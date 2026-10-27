"""Seal customer and project names and dates; project teams

Revision ID: 0009
Revises: 0008

A customer becomes a sealed container: its name and CVR, its sites' names and
its projects' names and dates move into the sealed values, encrypted with the
customer's own key, and the plain columns go. Existing rows are converted here,
so this needs the master key, as the app does. The sealing format is spelled out
below rather than imported, so later changes to app/crypto can't break it.
"""

import json
import os
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from alembic import op
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | None = None
depends_on: str | None = None

NONCE_LENGTH = 12


def _master_key() -> bytes:
    from app.settings import settings

    key = Path(settings.master_key_path).read_bytes()
    if len(key) != 32:
        raise RuntimeError("The master key must be 32 bytes.")
    return key


def _customer_key(master: bytes, customer_id: int, wrapped: bytes) -> bytes:
    context = f"ting/customer-key/{customer_id}".encode()
    return AESGCM(master).decrypt(wrapped[:NONCE_LENGTH], wrapped[NONCE_LENGTH:], context)


def _bound(customer_id: int, kind: str, record_id: int) -> bytes:
    return f"ting/customer/{customer_id}/{kind}/{record_id}".encode()


def _open(key: bytes, customer_id: int, kind: str, record_id: int, sealed: bytes
          ) -> dict[str, Any]:
    if not sealed:
        return {}
    data = AESGCM(key).decrypt(sealed[:NONCE_LENGTH], sealed[NONCE_LENGTH:],
                               _bound(customer_id, kind, record_id))
    value = json.loads(data)
    return value if isinstance(value, dict) else {}


def _seal(key: bytes, customer_id: int, kind: str, record_id: int, value: dict[str, Any]
          ) -> bytes:
    nonce = os.urandom(NONCE_LENGTH)
    data = json.dumps(value, separators=(",", ":"), sort_keys=True).encode()
    return nonce + AESGCM(key).encrypt(nonce, data, _bound(customer_id, kind, record_id))


def _date(value: Any) -> str | None:
    return str(value)[:10] if value else None


def _rows(sql: str) -> list[tuple[Any, ...]]:
    return [tuple(row) for row in op.get_bind().execute(sa.text(sql)).fetchall()]


def upgrade() -> None:
    conn = op.get_bind()
    # Plain ADD COLUMN, never a table rebuild (see 0003); DROP COLUMN below is in place too.
    op.add_column("projects", sa.Column("sealed", sa.LargeBinary(), nullable=False,
                                        server_default=sa.text("x''")))
    op.create_table(
        "project_members",
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="CASCADE"),
                  primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"),
                  primary_key=True),
        sa.Column("added_at", sa.DateTime(), nullable=False),
        sa.Column("added_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"),
                  nullable=True),
    )
    op.create_index("ix_project_members_user_id", "project_members", ["user_id"])

    customers = _rows("SELECT id, name, cvr, wrapped_key, sealed FROM customers")
    keys: dict[int, bytes] = {}
    if customers:
        master = _master_key()
        for customer_id, name, cvr, wrapped, sealed in customers:
            key = keys[customer_id] = _customer_key(master, customer_id, wrapped)
            address = _open(key, customer_id, "customer", customer_id, sealed).get("address", "")
            conn.execute(sa.text("UPDATE customers SET sealed = :sealed WHERE id = :id"), {
                "id": customer_id,
                "sealed": _seal(key, customer_id, "customer", customer_id,
                                {"name": name, "cvr": cvr, "address": address}),
            })
    for site_id, customer_id, name, sealed in _rows(
        "SELECT id, customer_id, name, sealed FROM customer_sites"
    ):
        key = keys[customer_id]
        address = _open(key, customer_id, "site", site_id, sealed).get("address", "")
        conn.execute(sa.text("UPDATE customer_sites SET sealed = :sealed WHERE id = :id"), {
            "id": site_id,
            "sealed": _seal(key, customer_id, "site", site_id,
                            {"name": name, "address": address}),
        })
    for project_id, customer_id, name, start, end in _rows(
        "SELECT id, customer_id, name, start_date, end_date FROM projects"
    ):
        conn.execute(sa.text("UPDATE projects SET sealed = :sealed WHERE id = :id"), {
            "id": project_id,
            "sealed": _seal(keys[customer_id], customer_id, "project", project_id, {
                "name": name, "start_date": _date(start), "end_date": _date(end),
            }),
        })

    op.drop_index("ix_customers_name", table_name="customers")
    for table, column in (("customers", "name"), ("customers", "cvr"),
                          ("customer_sites", "name"), ("projects", "name"),
                          ("projects", "start_date"), ("projects", "end_date")):
        op.execute(f"ALTER TABLE {table} DROP COLUMN {column}")


def downgrade() -> None:
    conn = op.get_bind()
    for table, column in (("customers", sa.Column("name", sa.String(200))),
                          ("customers", sa.Column("cvr", sa.String(8))),
                          ("customer_sites", sa.Column("name", sa.String(150))),
                          ("projects", sa.Column("name", sa.String(200))),
                          ("projects", sa.Column("start_date", sa.Date())),
                          ("projects", sa.Column("end_date", sa.Date()))):
        op.add_column(table, column)
    customers = _rows("SELECT id, wrapped_key, sealed FROM customers")
    keys: dict[int, bytes] = {}
    if customers:
        master = _master_key()
        for customer_id, wrapped, sealed in customers:
            key = keys[customer_id] = _customer_key(master, customer_id, wrapped)
            opened = _open(key, customer_id, "customer", customer_id, sealed)
            conn.execute(sa.text(
                "UPDATE customers SET name = :name, cvr = :cvr, sealed = :sealed WHERE id = :id"
            ), {"id": customer_id, "name": opened.get("name"), "cvr": opened.get("cvr"),
                "sealed": _seal(key, customer_id, "customer", customer_id,
                                {"address": opened.get("address", "")})})
    for site_id, customer_id, sealed in _rows("SELECT id, customer_id, sealed FROM customer_sites"):
        opened = _open(keys[customer_id], customer_id, "site", site_id, sealed)
        conn.execute(sa.text(
            "UPDATE customer_sites SET name = :name, sealed = :sealed WHERE id = :id"
        ), {"id": site_id, "name": opened.get("name"),
            "sealed": _seal(keys[customer_id], customer_id, "site", site_id,
                            {"address": opened.get("address", "")})})
    for project_id, customer_id, sealed in _rows("SELECT id, customer_id, sealed FROM projects"):
        opened = _open(keys[customer_id], customer_id, "project", project_id, sealed)
        conn.execute(sa.text(
            "UPDATE projects SET name = :name, start_date = :start, end_date = :end WHERE id = :id"
        ), {"id": project_id, "name": opened.get("name"), "start": opened.get("start_date"),
            "end": opened.get("end_date")})
    op.create_index("ix_customers_name", "customers", ["name"])
    op.drop_table("project_members")
    op.execute("ALTER TABLE projects DROP COLUMN sealed")
