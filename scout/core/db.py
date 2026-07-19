import sqlite3
from datetime import datetime, UTC
from pathlib import Path

from scout.core.migrations import MIGRATIONS

# Explicit adapters replace the deprecated built-in datetime adapter (Python 3.12+).
# Adapter: datetime → ISO-8601 string (timezone-aware datetimes include +00:00).
# Converter: raw bytes from DB → timezone-aware datetime (handles both old naive
#            strings and new aware strings for backwards compatibility).
sqlite3.register_adapter(datetime, lambda dt: dt.isoformat())
sqlite3.register_converter(
    "TIMESTAMP",
    lambda b: datetime.fromisoformat(b.decode()).replace(tzinfo=UTC)
    if "+" not in b.decode() and "Z" not in b.decode()
    else datetime.fromisoformat(b.decode()),
)


def connect(db_path: Path | str) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, isolation_level=None, detect_types=sqlite3.PARSE_DECLTYPES)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


def _current_version(conn: sqlite3.Connection) -> int:
    try:
        row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
        return int(row[0]) if row and row[0] is not None else 0
    except sqlite3.OperationalError:
        return 0


def migrate(conn: sqlite3.Connection) -> None:
    current = _current_version(conn)
    for i, sql in enumerate(MIGRATIONS, start=1):
        if i > current:
            conn.executescript(sql)
