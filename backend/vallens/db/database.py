from pathlib import Path
import sqlite3
from typing import Optional

SCHEMA_PATH = Path(__file__).parent / "schema.sql"


class Database:
    """ValLens local SQLite database manager."""

    def __init__(self, db_path: str | Path = "vallens.db"):
        self.db_path = str(db_path)
        self._memory_conn: Optional[sqlite3.Connection] = None

        if self.db_path == ":memory:":
            # Persist a single in-memory connection so tables are not lost between get_connection calls
            self._memory_conn = sqlite3.connect(":memory:")
            self._memory_conn.row_factory = sqlite3.Row
            self._memory_conn.execute("PRAGMA foreign_keys = ON;")

        self.init_db()

    def get_connection(self) -> sqlite3.Connection:
        if self._memory_conn is not None:
            return self._memory_conn

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA journal_mode = WAL;")
        return conn

    def init_db(self) -> None:
        """Initialize tables and indices if they do not exist."""
        with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
            schema_sql = f.read()

        conn = self.get_connection()
        conn.executescript(schema_sql)
        if self._memory_conn is None:
            conn.close()
