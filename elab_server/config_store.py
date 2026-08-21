"""Persistent configuration store for task metadata (alias, color overrides).

Used when a provider does NOT self-persist (persistConfig == false).
The dispatcher stores user-configurable settings keyed by the task's permanent ID.
"""
import os
import sqlite3
import logging
import threading
import time
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
        conn: Optional[sqlite3.Connection] = None
        try:
            conn = sqlite3.connect(self._db_path, check_same_thread=False)
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS task_config (
                    task_id TEXT PRIMARY KEY,
                    alias TEXT,
                    color TEXT,
                    updated_at REAL
                )
            """)

            # Migrate task_config to add decimals column if missing
            try:
                conn.execute("ALTER TABLE task_config ADD COLUMN decimals INTEGER;")
                logger.info("Migrated task_config: added decimals column.")
            except sqlite3.OperationalError:
                # Column already exists
                pass

            # Provider credentials for HMAC-based authentication.
            # status: 'pending' | 'approved' | 'revoked'
            # manifest_hash: SHA-256 hex digest of canonicalized manifest at approval time
            # secret_hex: 32-byte secret used for HMAC-SHA256 over data_stream payloads
            conn.execute("""
                CREATE TABLE IF NOT EXISTS provider_credentials (
                    device_id TEXT PRIMARY KEY,
                    secret_hex TEXT NOT NULL,
                    manifest_hash TEXT,
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at REAL NOT NULL,
                    approved_at REAL,
                    last_seen_at REAL,
                    last_client_ip TEXT,
                    notes TEXT
                )
            """)
            conn.commit()
        except sqlite3.Error:
            logger.exception("ConfigStore: failed to initialise database at %s", self._db_path)
            if conn is not None:
                try:
                    conn.close()
                except sqlite3.Error:
                    pass
            self._conn = None
            raise
        self._conn = conn
        logger.info("ConfigStore initialized at %s", self._db_path)

    def _require_conn(self) -> sqlite3.Connection:
        """Return the live SQLite connection or raise if it's been closed.

        Replaces the previous ``assert self._conn is not None`` pattern which
        is silently removed when Python runs with ``-O``.
        """
        conn = self._conn
        if conn is None:
            raise RuntimeError("ConfigStore: database connection is not initialised")
        return conn

    def get_task_config(self, task_id: str) -> Dict[str, Any]:
        """Return stored overrides for a task (alias, color, decimals). Empty dict if none."""
        with self._lock:
            cursor = self._require_conn().execute(
                "SELECT alias, color, decimals FROM task_config WHERE task_id = ?",
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
        if row[2] is not None:
            result["decimals"] = row[2]
        return result

    def set_task_alias(self, task_id: str, alias: Optional[str]) -> None:
        """Store or clear the alias for a task."""
        with self._lock:
            conn = self._require_conn()
            conn.execute(
                """INSERT INTO task_config (task_id, alias, updated_at)
                   VALUES (?, ?, ?)
                   ON CONFLICT(task_id) DO UPDATE SET alias = excluded.alias, updated_at = excluded.updated_at""",
                (task_id, alias, time.time()),
            )
            conn.commit()
        logger.debug("ConfigStore: alias for %s set to %r", task_id, alias)

    def set_task_color(self, task_id: str, color: Optional[str]) -> None:
        """Store or clear the color override for a task."""
        with self._lock:
            conn = self._require_conn()
            conn.execute(
                """INSERT INTO task_config (task_id, color, updated_at)
                   VALUES (?, ?, ?)
                   ON CONFLICT(task_id) DO UPDATE SET color = excluded.color, updated_at = excluded.updated_at""",
                (task_id, color, time.time()),
            )
            conn.commit()
        logger.debug("ConfigStore: color for %s set to %r", task_id, color)

    def set_task_decimals(self, task_id: str, decimals: Optional[int]) -> None:
        """Store or clear the decimals override for a task."""
        with self._lock:
            conn = self._require_conn()
            conn.execute(
                """INSERT INTO task_config (task_id, decimals, updated_at)
                   VALUES (?, ?, ?)
                   ON CONFLICT(task_id) DO UPDATE SET decimals = excluded.decimals, updated_at = excluded.updated_at""",
                (task_id, decimals, time.time()),
            )
            conn.commit()
        logger.debug("ConfigStore: decimals for %s set to %r", task_id, decimals)

    def get_all_configs(self) -> Dict[str, Dict[str, Any]]:
        """Return all stored task configs as {task_id: {alias, color, decimals}}."""
        with self._lock:
            cursor = self._require_conn().execute(
                "SELECT task_id, alias, color, decimals FROM task_config"
            )
            rows = cursor.fetchall()
        result: Dict[str, Dict[str, Any]] = {}
        for task_id, alias, color, decimals in rows:
            entry: Dict[str, Any] = {}
            if alias is not None:
                entry["alias"] = alias
            if color is not None:
                entry["color"] = color
            if decimals is not None:
                entry["decimals"] = decimals
            if entry:
                result[task_id] = entry
        return result

    def close(self) -> None:
        """Close the database connection."""
        with self._lock:
            if self._conn:
                self._conn.close()
                self._conn = None

    # ------------------------------------------------------------------
    # Provider credential management (HMAC pairing)
    # ------------------------------------------------------------------

    def get_credential(self, device_id: str) -> Optional[Dict[str, Any]]:
        """Return the credential row for ``device_id`` or ``None``."""
        with self._lock:
            cursor = self._require_conn().execute(
                """SELECT device_id, secret_hex, manifest_hash, status,
                          created_at, approved_at, last_seen_at, last_client_ip, notes
                     FROM provider_credentials WHERE device_id = ?""",
                (device_id,),
            )
            row = cursor.fetchone()
        if row is None:
            return None
        return {
            "device_id": row[0],
            "secret_hex": row[1],
            "manifest_hash": row[2],
            "status": row[3],
            "created_at": row[4],
            "approved_at": row[5],
            "last_seen_at": row[6],
            "last_client_ip": row[7],
            "notes": row[8],
        }

    def upsert_pending_credential(
        self,
        device_id: str,
        secret_hex: str,
        manifest_hash: str,
        client_ip: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Insert a pending credential or reset an existing one to pending state.

        If the device is already approved with the same manifest_hash, this is a no-op
        and returns the existing row. If the manifest_hash differs, the device is
        forced back to pending and must be re-approved.
        """
        now = time.time()
        with self._lock:
            conn = self._require_conn()
            cursor = conn.execute(
                "SELECT status, manifest_hash, secret_hex, created_at FROM provider_credentials WHERE device_id = ?",
                (device_id,),
            )
            existing = cursor.fetchone()
            if existing is None:
                conn.execute(
                    """INSERT INTO provider_credentials
                          (device_id, secret_hex, manifest_hash, status, created_at, last_seen_at, last_client_ip)
                       VALUES (?, ?, ?, 'pending', ?, ?, ?)""",
                    (device_id, secret_hex, manifest_hash, now, now, client_ip),
                )
            else:
                existing_status, existing_hash, _existing_secret, _existing_created = existing
                if existing_status == "approved" and existing_hash == manifest_hash:
                    # already approved, just refresh last_seen
                    conn.execute(
                        "UPDATE provider_credentials SET last_seen_at = ?, last_client_ip = ? WHERE device_id = ?",
                        (now, client_ip, device_id),
                    )
                else:
                    # manifest changed or was revoked â†’ reset to pending, new secret
                    conn.execute(
                        """UPDATE provider_credentials
                              SET secret_hex = ?, manifest_hash = ?, status = 'pending',
                                  last_seen_at = ?, last_client_ip = ?, approved_at = NULL
                            WHERE device_id = ?""",
                        (secret_hex, manifest_hash, now, client_ip, device_id),
                    )
            conn.commit()
        result = self.get_credential(device_id)
        if result is None:
            raise RuntimeError("ConfigStore: upsert succeeded but credential could not be re-read")
        return result

    def approve_credential(self, device_id: str, manifest_hash: str) -> bool:
        """Mark a pending credential as approved. Returns False if not found."""
        with self._lock:
            conn = self._require_conn()
            cursor = conn.execute(
                "SELECT manifest_hash FROM provider_credentials WHERE device_id = ?",
                (device_id,),
            )
            row = cursor.fetchone()
            if row is None:
                return False
            if row[0] != manifest_hash:
                logger.warning(
                    "approve_credential: manifest_hash mismatch for %s (expected %s, got %s)",
                    device_id, row[0], manifest_hash,
                )
                return False
            conn.execute(
                """UPDATE provider_credentials
                      SET status = 'approved', approved_at = ?
                    WHERE device_id = ?""",
                (time.time(), device_id),
            )
            conn.commit()
        logger.info("Provider %s approved", device_id)
        return True

    def revoke_credential(self, device_id: str) -> bool:
        """Mark a credential as revoked. Returns False if not found."""
        with self._lock:
            conn = self._require_conn()
            cursor = conn.execute(
                "UPDATE provider_credentials SET status = 'revoked' WHERE device_id = ?",
                (device_id,),
            )
            conn.commit()
            return cursor.rowcount > 0

    def delete_credential(self, device_id: str) -> bool:
        """Delete a credential entry completely. Returns False if not found."""
        with self._lock:
            conn = self._require_conn()
            cursor = conn.execute(
                "DELETE FROM provider_credentials WHERE device_id = ?",
                (device_id,),
            )
            conn.commit()
            return cursor.rowcount > 0

    def list_credentials(self, status: Optional[str] = None) -> list:
        """List credentials, optionally filtered by status."""
        with self._lock:
            conn = self._require_conn()
            if status is None:
                cursor = conn.execute(
                    """SELECT device_id, manifest_hash, status, created_at,
                              approved_at, last_seen_at, last_client_ip
                         FROM provider_credentials ORDER BY created_at DESC"""
                )
            else:
                cursor = conn.execute(
                    """SELECT device_id, manifest_hash, status, created_at,
                              approved_at, last_seen_at, last_client_ip
                         FROM provider_credentials WHERE status = ?
                         ORDER BY created_at DESC""",
                    (status,),
                )
            rows = cursor.fetchall()
        return [
            {
                "device_id": r[0],
                "manifest_hash": r[1],
                "status": r[2],
                "created_at": r[3],
                "approved_at": r[4],
                "last_seen_at": r[5],
                "last_client_ip": r[6],
            }
            for r in rows
        ]
