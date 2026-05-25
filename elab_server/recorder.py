"""This module contains the SessionRecorder class."""
import os
import json
import time
import sqlite3
import logging
import threading
from datetime import datetime
from .config import SESSION_DIR
from .session_utils import list_recorded_sessions

logger = logging.getLogger(__name__)

# pylint: disable=too-many-instance-attributes
class SessionRecorder:
    """A class to record session data to a SQLite database."""
    def __init__(self, state, socketio):
        self.state = state
        self.socketio = socketio
        self.conn = None
        self.cursor = None
        self.db_path = None
        self.buffer = []
        # Tunables: flush when buffer fills OR after a short time window so
        # low-rate streams don't sit unwritten for ages, and high-rate streams
        # don't lock the disk on every event.
        self.buffer_size = 200
        self.flush_interval = 0.5  # seconds
        self.last_flush = 0.0
        # SQLite is opened with check_same_thread=False; serialize writes
        # ourselves to avoid corruption under gevent/multiple writers.
        self._write_lock = threading.Lock()

    def start(self, session_id_from_client=None):
        """Starts a new recording session."""
        if self.state.recording:
            return {'error': 'Already recording'}

        # Use the timestamp-prefixed session naming format expected by the UI.
        time_str = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        if session_id_from_client and session_id_from_client.strip():
            session_id = f"{time_str}_{session_id_from_client.strip()}"
        else:
            session_id = time_str

        session_dir = os.path.join(SESSION_DIR, session_id)
        os.makedirs(session_dir, exist_ok=True)

        self.db_path = os.path.join(session_dir, "session.sqlite")
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.cursor = self.conn.cursor()
        self.cursor.execute("PRAGMA journal_mode=WAL;")

        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS session_log (
                seq INTEGER PRIMARY KEY AUTOINCREMENT, event_time_ms REAL, source_id TEXT,
                distribution TEXT, type TEXT, payload TEXT, binary_data BLOB, ingest_ts REAL
            )
        """)
        self.cursor.execute("CREATE INDEX IF NOT EXISTS idx_time ON session_log(event_time_ms)")

        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS manifests (
                provider_id TEXT PRIMARY KEY, manifest TEXT
            )
        """)
        # Only persist manifests for tasks that are currently active.
        manifests_to_store = {}
        with self.state.atomic_update():
            active_task_ids = list(self.state.active_tasks_by_slot.values())
        for task_id in active_task_ids:
            # Resolve the full provider manifest that owns the active task.
            provider_manifest = self.state.get_provider_manifest(task_id)
            if provider_manifest:
                # Use the provider ID as the deduplication key.
                manifests_to_store[provider_manifest['id']] = provider_manifest

        if manifests_to_store:
            manifest_data = [
                (pid, json.dumps(m)) for pid, m in manifests_to_store.items()
            ]
            self.cursor.executemany(
                "INSERT OR IGNORE INTO manifests (provider_id, manifest) VALUES (?, ?)",
                manifest_data,
            )

        self.conn.commit()

        self.state.current_session_id = session_id
        self.state.recording = True
        self.buffer = []
        self.last_flush = time.time()

        self.write({
            "type": "SESSION_START",
            "timestamp": time.time() * 1000,
            "session_id": session_id,
        })

        logger.info(
            "🎬 Recording started (SQLite): %s. Stored manifests for %d active providers.",
            session_id,
            len(manifests_to_store),
        )
        self.socketio.emit(
            'session_status',
            {'recording': True, 'session_id': session_id},
            room='ui_clients',
        )
        return {'session_id': session_id, 'status': 'started'}

    def write(self, event, binary_blob=None):
        """
        Writes an event to the database buffer.

        binary_blob can contain optional bytes, such as JPEG data, for
        efficient BLOB storage.
        """
        if not self.state.recording or not self.conn:
            return

        payload = event.get('payload', {})
        dist = payload.get('distribution', 'discrete')

        if event.get('type') == 'DATA_STREAM':
            if dist == 'linear':
                evt_time = payload.get('startTime', time.time() * 1000)
            else:
                evt_time = payload.get('timestamp', time.time() * 1000)
        else:
            evt_time = event.get('timestamp', time.time() * 1000)

        now = time.time()
        with self._write_lock:
            self.buffer.append((
                evt_time,
                payload.get('sourceId', 'system'),
                dist,
                event.get('type', 'UNKNOWN'),
                json.dumps(event),  # JSON payload, potentially without the base64 blob.
                binary_blob,        # Binary asset stored as a BLOB.
                now,
            ))

            # Flush either when the buffer is full or after the time window.
            if (
                len(self.buffer) >= self.buffer_size
                or (self.buffer and now - self.last_flush >= self.flush_interval)
            ):
                self._flush_locked()

    def _flush(self):
        """Flushes the buffer to the database (thread-safe wrapper)."""
        with self._write_lock:
            self._flush_locked()

    def _flush_locked(self):
        """Flush implementation; assumes self._write_lock is held."""
        if not self.conn or not self.cursor or not self.buffer:
            return
        try:
            self.cursor.executemany(
                """
                INSERT INTO session_log (
                    event_time_ms, source_id, distribution, type,
                    payload, binary_data, ingest_ts
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                self.buffer,
            )
            self.conn.commit()
            self.buffer = []
            self.last_flush = time.time()
        except sqlite3.Error as e:
            logger.error("DB Write Error: %s", e)

    def stop(self):
        """Stops the current recording session."""
        if not self.state.recording:
            return {'error': 'Not recording'}

        self.write({"type": "SESSION_END", "timestamp": time.time() * 1000})
        self._flush()

        if self.conn:
            self.conn.close()
            self.conn = None

        sid = self.state.current_session_id
        self.state.recording = False
        self.state.current_session_id = None

        logger.info("⏹️ Recording stopped: %s", sid)
        self.socketio.emit('session_status', {'recording': False}, room='ui_clients')

        # Refresh the session list after recording stops.
        try:
            sessions = list_recorded_sessions(SESSION_DIR)
            self.socketio.emit('session_list', sessions, room='ui_clients')
            logger.debug("🔄 Emitted updated session list to all clients.")
        except OSError as e:
            logger.error("Failed to emit updated session list: %s", e)

        return {'status': 'stopped', 'session_id': sid}

    def add_manifest_if_recording(self, task_id):
        """Adds a manifest to the current recording if a new task is assigned."""
        if not self.state.recording or not self.conn or not self.cursor:
            return

        provider_manifest = self.state.get_provider_manifest(task_id)
        if provider_manifest:
            try:
                manifest_data = (provider_manifest['id'], json.dumps(provider_manifest))
                self.cursor.execute(
                    "INSERT OR IGNORE INTO manifests (provider_id, manifest) VALUES (?, ?)",
                    manifest_data,
                )
                self.conn.commit()
                logger.debug(
                    "📝 Added new manifest for provider %s to ongoing recording %s.",
                    provider_manifest['id'],
                    self.state.current_session_id
                )
            except sqlite3.Error as e:
                logger.error("DB Write Error on adding manifest: %s", e)
