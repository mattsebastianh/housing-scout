import sqlite3
from pathlib import Path

from scout.core.db import connect, migrate


def test_migrate_creates_all_tables(tmp_path):
    """Migration creates all expected schema tables."""
    db_path = tmp_path / "test.db"
    conn = connect(db_path)
    migrate(conn)
    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    expected = {
        "schema_version",
        "raw_listings",
        "properties",
        "property_raw_link",
        "exclusions",
        "enrichments",
        "runs",
        "scores",
    }
    assert expected <= tables


def test_migrate_is_idempotent(tmp_path):
    """Running migrate twice does not raise and records exactly the expected version rows."""
    db_path = tmp_path / "test.db"
    conn = connect(db_path)
    migrate(conn)
    migrate(conn)  # second call should not raise
    versions = [row[0] for row in conn.execute("SELECT version FROM schema_version ORDER BY version")]
    assert versions == [1, 2]


def test_wal_mode_enabled(tmp_path):
    """connect() enables WAL journal mode on the SQLite database."""
    db_path = tmp_path / "test.db"
    conn = connect(db_path)
    mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode.lower() == "wal"
