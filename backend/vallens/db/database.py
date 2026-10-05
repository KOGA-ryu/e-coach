from pathlib import Path
import sqlite3
from typing import Optional

SCHEMA_PATH = Path(__file__).parent / "schema.sql"


class Database:
    """ValLens local SQLite database manager."""

    def __init__(self, db_path: str | Path = "vallens.db"):
        self.db_path = Path(db_path)
        self.init_db()

    def get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA journal_mode = WAL;")
        return conn

    def init_db(self) -> None:
        """Initialize tables and indices if they do not exist."""
        with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
            schema_sql = f.read()

        with self.get_connection() as conn:
            conn.executescript(schema_sql)
