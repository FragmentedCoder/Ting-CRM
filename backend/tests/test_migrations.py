from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import text

import app.models  # noqa: F401
from app.db import Base, make_engine
from app.migrate import upgrade


def _pragma_agrees(conn, removed, added) -> bool:
    """SQLAlchemy reads ON DELETE only from table-level FOREIGN KEY clauses, but a
    column added later (ALTER TABLE ... ADD COLUMN ... REFERENCES) can only have a
    column-level one; it is reflected without it, so a remove_fk/add_fk pair turns
    up. Such a pair is no difference if SQLite's own record of the key agrees with
    the model in every part."""
    model = added[1]
    if (removed[1].table.name != model.table.name
            or [c.name for c in removed[1].columns] != [c.name for c in model.columns]):
        return False
    rows = conn.exec_driver_sql(f"PRAGMA foreign_key_list({model.table.name})").all()
    return any(
        (row[2], row[3], row[4], row[6]) == (
            model.referred_table.name, model.columns[0].name, model.elements[0].column.name,
            (model.ondelete or "NO ACTION").upper())
        for row in rows
    )


def test_the_migrations_build_exactly_the_schema_the_models_describe(engine) -> None:
    with engine.connect() as conn:
        differences = compare_metadata(MigrationContext.configure(conn), Base.metadata)
        removed = [d for d in differences if d[0] == "remove_fk"]
        added = [d for d in differences if d[0] == "add_fk"]
        explained = [(r, a) for r in removed for a in added if _pragma_agrees(conn, r, a)]
    for pair in explained:
        differences = [d for d in differences if d not in pair]
    assert differences == []


def test_tables_whose_ids_reach_the_audit_log_never_reuse_an_id(engine) -> None:
    # compare_metadata doesn't look at AUTOINCREMENT, so check the migrations directly.
    autoincrement = {
        table.name for table in Base.metadata.tables.values()
        if table.kwargs.get("sqlite_autoincrement")
    }
    assert autoincrement == {
        "users", "user_sessions", "mfa_factors", "customers", "customer_sites",
        "customer_contacts", "projects", "jobs", "audit_stamps",
    }
    with engine.connect() as conn:
        for name in autoincrement:
            sql = conn.execute(
                text("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = :n"),
                {"n": name},
            ).scalar()
            assert "AUTOINCREMENT" in sql, name


def test_upgrading_keeps_existing_rows(data_dir, master_key_path) -> None:
    """SQLite rebuilds a table to change some constraints, and dropping the old copy
    with foreign keys on deletes every row that cascades from it. Data must survive."""
    engine = make_engine(data_dir, master_key_path)
    upgrade(engine, "0002")
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO users (id, username, display_name, is_active, failed_sign_ins, created_at)"
            " VALUES (1, 'astrid', 'Astrid', 1, 0, '2026-10-24 12:00:00')"
        ))
        conn.execute(text(
            "INSERT INTO user_sessions (token_hash, user_id, created_at, last_seen_at, expires_at)"
            " VALUES ('h', 1, '2026-10-24 12:00:00', '2026-10-24 12:00:00', '2026-10-25')"
        ))

    upgrade(engine)

    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM users")).scalar() == 1
        assert conn.execute(text("SELECT count(*) FROM user_sessions")).scalar() == 1
    engine.dispose()


def test_existing_customers_and_projects_are_sealed_on_upgrade(data_dir, master_key_path) -> None:
    """0009 moves names and dates already stored in the clear into the sealed values."""
    from sqlalchemy.orm import Session

    from app.crypto.keys import generate_key, load_master_key, wrap_key
    from app.crypto.sealing import seal
    from app.customers import Customer, Keyring, bound_to

    engine = make_engine(data_dir, master_key_path)
    upgrade(engine, "0008")
    key = generate_key()
    wrapped = wrap_key(load_master_key(master_key_path), key, context=b"ting/customer-key/1")
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO customers (id, name, cvr, wrapped_key, sealed, language,"
            " retention_months, created_at) VALUES (1, 'Nordlys IT ApS', '12345678', :w, :s,"
            " 'da', 12, '2026-10-24 12:00:00')"
        ), {"w": wrapped, "s": seal(key, {"address": "Fjordvej 1"},
                                       bound_to=bound_to(1, "customer", 1))})
        conn.execute(text(
            "INSERT INTO customer_sites (id, customer_id, name, sealed) VALUES (1, 1, 'HQ', :s)"
        ), {"s": seal(key, {"address": "Fjordvej 1"}, bound_to=bound_to(1, "site", 1))})
        conn.execute(text(
            "INSERT INTO projects (id, customer_id, number, name, start_date, classification,"
            " created_at) VALUES (1, 1, 'P-2026-0001', 'Incident', '2026-10-20', 'TLP:RED',"
            " '2026-10-24 12:00:00')"
        ))

    upgrade(engine)

    with Session(engine) as db:
        customer = db.get(Customer, 1)
        keyring = Keyring()
        assert keyring.details(customer) == {
            "name": "Nordlys IT ApS", "cvr": "12345678", "address": "Fjordvej 1"}
        sealer = keyring.sealer(customer)
        site = db.execute(text("SELECT sealed FROM customer_sites")).scalar()
        assert sealer.open("site", 1, site) == {"name": "HQ", "address": "Fjordvej 1"}
        project = db.execute(text("SELECT sealed FROM projects")).scalar()
        assert sealer.open("project", 1, project) == {
            "name": "Incident", "start_date": "2026-10-20", "end_date": None}
        db.commit()
    engine.dispose()


def test_assignments_and_team_members_keep_what_people_can_be_on_upgrade(
    data_dir, master_key_path
) -> None:
    """0011 records what each assignment and team member is there as, from roles."""
    engine = make_engine(data_dir, master_key_path)
    upgrade(engine, "0010")
    at = "2026-10-24 12:00:00"
    with engine.begin() as conn:
        for user_id, name in ((1, "tor"), (2, "rikke"), (3, "bjorn")):
            conn.execute(text(
                "INSERT INTO users (id, username, display_name, is_active, failed_sign_ins,"
                " created_at) VALUES (:i, :n, :n, 1, 0, :at)"), {"i": user_id, "n": name, "at": at})
        for user_id, role in ((1, "technician"), (2, "reviewer"), (3, "technician"),
                              (3, "reviewer")):
            conn.execute(text("INSERT INTO user_roles (user_id, role, granted_at)"
                              " VALUES (:u, :r, :at)"), {"u": user_id, "r": role, "at": at})
        conn.execute(text(
            "INSERT INTO customers (id, wrapped_key, sealed, language, retention_months,"
            " created_at) VALUES (1, x'00', x'00', 'da', 12, :at)"), {"at": at})
        conn.execute(text(
            "INSERT INTO projects (id, customer_id, number, sealed, classification, created_at)"
            " VALUES (1, 1, 'P-2026-0001', x'00', 'TLP:RED', :at)"), {"at": at})
        for user_id in (1, 2, 3):
            conn.execute(text("INSERT INTO customer_assignments (customer_id, user_id,"
                              " assigned_at) VALUES (1, :u, :at)"), {"u": user_id, "at": at})
            conn.execute(text("INSERT INTO project_members (project_id, user_id, added_at)"
                              " VALUES (1, :u, :at)"), {"u": user_id, "at": at})

    upgrade(engine)

    with engine.connect() as conn:
        assigned = conn.execute(text("SELECT user_id, as_technician, as_reviewer"
                                     " FROM customer_assignments ORDER BY user_id"))
        assert [tuple(row) for row in assigned] == [(1, 1, 0), (2, 0, 1), (3, 1, 1)]
        members = conn.execute(text("SELECT user_id, as_role FROM project_members"
                                    " ORDER BY user_id"))
        assert [tuple(row) for row in members] == [
            (1, "technician"), (2, "reviewer"), (3, "technician")]
    engine.dispose()
