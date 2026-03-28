"""Lightweight async-friendly SQLite helper for simulation platforms.

All platforms persist state to per-run SQLite databases.  This module
provides a thin wrapper that:

* Applies performance PRAGMAs (synchronous=OFF, journal_mode=WAL).
* Loads table schemas from ``.sql`` files in the ``schema/`` directory.
* Exposes ``execute`` / ``executemany`` / ``fetchone`` / ``fetchall``
  with automatic connection management.
"""

import logging
import os
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

logger = logging.getLogger(__name__)

# Directory containing the .sql schema files shipped with this package.
SCHEMA_DIR = Path(__file__).resolve().parent / "schema"


class Database:
    """SQLite database wrapper for a single simulation run.

    Args:
        db_path: File path for the SQLite database.  Use ``":memory:"``
            for an ephemeral in-memory database (useful for tests).
    """

    def __init__(self, db_path: str = ":memory:") -> None:
        self.db_path = db_path
        self._conn: Optional[sqlite3.Connection] = None

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    @property
    def conn(self) -> sqlite3.Connection:
        """Lazily open (and configure) the connection."""
        if self._conn is None:
            self._conn = sqlite3.connect(self.db_path)
            self._conn.row_factory = sqlite3.Row
            # Performance PRAGMAs — safe for single-writer simulation use.
            self._conn.execute("PRAGMA synchronous = OFF")
            self._conn.execute("PRAGMA journal_mode = WAL")
            self._conn.execute("PRAGMA cache_size = -8000")  # 8 MB
            self._conn.execute("PRAGMA temp_store = MEMORY")
        return self._conn

    def close(self) -> None:
        """Commit outstanding changes and close the connection."""
        if self._conn is not None:
            try:
                self._conn.commit()
            except sqlite3.ProgrammingError:
                pass
            self._conn.close()
            self._conn = None

    # ------------------------------------------------------------------
    # Schema helpers
    # ------------------------------------------------------------------

    def load_schema(self, schema_name: str) -> None:
        """Execute a ``.sql`` file from the built-in ``schema/`` directory.

        Args:
            schema_name: Bare name without extension, e.g. ``"user"``
                which resolves to ``schema/user.sql``.
        """
        sql_path = SCHEMA_DIR / f"{schema_name}.sql"
        if not sql_path.exists():
            raise FileNotFoundError(f"Schema file not found: {sql_path}")
        sql = sql_path.read_text(encoding="utf-8")
        self.conn.executescript(sql)
        logger.debug("Loaded schema %s from %s", schema_name, sql_path)

    def load_schemas(self, names: Sequence[str]) -> None:
        """Load multiple schemas in order."""
        for name in names:
            self.load_schema(name)

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    def execute(
        self,
        sql: str,
        params: Union[Tuple, Dict[str, Any], None] = None,
        commit: bool = True,
    ) -> sqlite3.Cursor:
        """Execute a single SQL statement.

        Args:
            sql: SQL string, optionally with ``?`` or ``:name`` placeholders.
            params: Bind parameters (tuple or dict).
            commit: Whether to auto-commit after execution.

        Returns:
            The ``sqlite3.Cursor`` produced by the statement.
        """
        cursor = self.conn.execute(sql, params or ())
        if commit:
            self.conn.commit()
        return cursor

    def executemany(
        self,
        sql: str,
        params_seq: Sequence[Union[Tuple, Dict[str, Any]]],
        commit: bool = True,
    ) -> sqlite3.Cursor:
        """Execute a statement against every parameter set in *params_seq*."""
        cursor = self.conn.executemany(sql, params_seq)
        if commit:
            self.conn.commit()
        return cursor

    def fetchone(
        self,
        sql: str,
        params: Union[Tuple, Dict[str, Any], None] = None,
    ) -> Optional[sqlite3.Row]:
        """Execute *sql* and return the first row, or ``None``."""
        return self.conn.execute(sql, params or ()).fetchone()

    def fetchall(
        self,
        sql: str,
        params: Union[Tuple, Dict[str, Any], None] = None,
    ) -> List[sqlite3.Row]:
        """Execute *sql* and return all rows."""
        return self.conn.execute(sql, params or ()).fetchall()

    def table_exists(self, table_name: str) -> bool:
        """Check whether a table already exists in the database."""
        row = self.fetchone(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table_name,),
        )
        return row is not None

    # ------------------------------------------------------------------
    # Dunder helpers
    # ------------------------------------------------------------------

    def __enter__(self) -> "Database":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    def __del__(self) -> None:
        self.close()
