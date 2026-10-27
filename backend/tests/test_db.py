import sqlite3

import pytest
import sqlcipher3
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.db import check_integrity, make_engine, reading


def test_the_database_file_is_encrypted_at_rest(data_dir, master_key_path) -> None:
    engine = make_engine(data_dir, master_key_path)
    with engine.connect() as conn:
        conn.execute(text("CREATE TABLE t (x TEXT)"))
        conn.execute(text("INSERT INTO t VALUES ('plaintext-marker')"))
        conn.commit()
    engine.dispose()

    raw = (data_dir / "ting.db").read_bytes()
    assert not raw.startswith(b"SQLite format 3")
    assert b"plaintext-marker" not in raw

    try:
        plain = sqlite3.connect(str(data_dir / "ting.db"))
        plain.execute("SELECT count(*) FROM sqlite_master").fetchone()
        plain_sqlite_opened = True
    except sqlite3.DatabaseError:
        plain_sqlite_opened = False
    assert not plain_sqlite_opened


def test_reopening_reuses_the_same_key_and_data(data_dir, master_key_path) -> None:
    engine_1 = make_engine(data_dir, master_key_path)
    with engine_1.connect() as conn:
        conn.execute(text("CREATE TABLE t (x INTEGER)"))
        conn.execute(text("INSERT INTO t VALUES (1)"))
        conn.commit()
    engine_1.dispose()

    engine_2 = make_engine(data_dir, master_key_path)
    with engine_2.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM t")).scalar() == 1
    engine_2.dispose()


def test_every_transaction_takes_the_write_lock_when_it_begins(data_dir, master_key_path) -> None:
    engine = make_engine(data_dir, master_key_path)
    with engine.connect() as holder:
        holder.execute(text("SELECT 1"))  # begins a transaction that writes nothing
        other = engine.raw_connection()
        try:
            other.driver_connection.execute("PRAGMA busy_timeout = 100")
            with pytest.raises(sqlcipher3.OperationalError, match="locked"):
                other.driver_connection.execute("BEGIN IMMEDIATE")
        finally:
            other.close()
    engine.dispose()


def test_long_reads_take_no_write_lock(data_dir, master_key_path) -> None:
    engine = make_engine(data_dir, master_key_path)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE t (x INTEGER)"))
        conn.execute(text("INSERT INTO t VALUES (1)"))
    with reading(engine) as reader:
        assert reader.execute(text("SELECT count(*) FROM t")).scalar() == 1
        other = engine.raw_connection()
        try:
            other.driver_connection.execute("PRAGMA busy_timeout = 100")
            other.driver_connection.execute("BEGIN IMMEDIATE")
            other.driver_connection.execute("INSERT INTO t VALUES (2)")
            other.driver_connection.execute("COMMIT")
        finally:
            other.close()
        # The reader keeps the snapshot it started with.
        assert reader.execute(text("SELECT count(*) FROM t")).scalar() == 1
    engine.dispose()


def test_driver_errors_surface_as_sqlalchemy_errors(data_dir, master_key_path) -> None:
    engine = make_engine(data_dir, master_key_path)
    with engine.connect() as conn:
        conn.execute(text("CREATE TABLE t (x TEXT UNIQUE)"))
        conn.execute(text("INSERT INTO t VALUES ('a')"))
        with pytest.raises(IntegrityError):
            conn.execute(text("INSERT INTO t VALUES ('a')"))
    engine.dispose()


def test_check_integrity_reports_no_problems_on_a_fresh_database(engine) -> None:
    assert check_integrity(engine) == []
