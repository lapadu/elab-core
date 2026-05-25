"""Persistent configuration store for task metadata (alias, color overrides).

Used when a provider does NOT self-persist (persistConfig == false).
The dispatcher stores user-configurable settings keyed by the task's permanent ID.
"""
import os
import sqlite3
import logging
import threading
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Default path for the configuration database (next to the server module).
_DEFAULT_DB_DIR = os.path.dirname(os.path.abspath(__file__))
_DB_FILENAME = "elab_config.sqlite"


class ConfigStore:
    """Thread-safe SQLite-backed configuration store for task overrides."""

    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            db_path = os.path.join(
                os.environ.get("ELAB_CONFIG_DIR", _DEFAULT_DB_DIR),
                _DB_FILENAME,
            )
        self._db_path = db_path
        self._lock = threading.Lock()
        self._conn: Optional[sqlite3.Connection] = None
        self._init_db()

    def _init_db(self) -> None:
        """Create the database and tables if they don't exist."""
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS task_config (
                task_id TEXT PRIMARY KEY,
                alias TEXT,
                color TEXT,
                updated_at REAL
            )
        """)
        self._conn.commit()
        logger.info("ConfigStore initialized at %s", self._db_path)

    def get_task_config(self, task_id: str) -> Dict[str, Any]:
        """Return stored overrides for a task (alias, color). Empty dict if none."""
        with self._lock:
            assert self._conn is not None
            cursor = self._conn.execute(
                "SELECT alias, color FROM task_config WHERE task_id = ?",
                (task_id,),
            )
            row = cursor.fetchone()
        if row is None:
            return {}
        result: Dict[str, Any] = {}
        if row[0] is not None:
            result["alias"] = row[0]
        if row[1] is not None:
            result["color"] = row[1]
        return result

    def set_task_alias(self, task_id: str, alias: Optional[str]) -> None:
        """Store or clear the alias for a task."""
        import time
        with self._lock:
            assert self._conn is not None
            self._conn.execute(
                """INSERT INTO task_config (task_id, alias, updated_at)
                   VALUES (?, ?, ?)
                   ON CONFLICT(task_id) DO UPDATE SET alias = excluded.alias, updated_at = excluded.updated_at""",
                (task_id, alias, time.time()),
            )
            self._conn.commit()
        logger.debug("ConfigStore: alias for %s set to %r", task_id, alias)

    def set_task_color(self, task_id: str, color: Optional[str]) -> None:
        """Store or clear the color override for a task."""
        import time
        with self._lock:
            assert self._conn is not None
            self._conn.execute(
                """INSERT INTO task_config (task_id, color, updated_at)
                   VALUES (?, ?, ?)
                   ON CONFLICT(task_id) DO UPDATE SET color = excluded.color, updated_at = excluded.updated_at""",
                (task_id, color, time.time()),
            )
            self._conn.commit()
        logger.debug("ConfigStore: color for %s set to %r", task_id, color)

    def get_all_configs(self) -> Dict[str, Dict[str, Any]]:
        """Return all stored task configs as {task_id: {alias, color}}."""
        with self._lock:
            assert self._conn is not None
            cursor = self._conn.execute(
                "SELECT task_id, alias, color FROM task_config"
            )
            rows = cursor.fetchall()
        result: Dict[str, Dict[str, Any]] = {}
        for task_id, alias, color in rows:
            entry: Dict[str, Any] = {}
            if alias is not None:
                entry["alias"] = alias
            if color is not None:
                entry["color"] = color
            if entry:
                result[task_id] = entry
        return result

    def close(self) -> None:
        """Close the database connection."""
        with self._lock:
            if self._conn:
                self._conn.close()
                self._conn = None
