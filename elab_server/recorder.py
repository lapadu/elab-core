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

# Bumped when the on-disk session layout changes in a way readers must know.
SESSION_SCHEMA_VERSION = 1

# How a source's timestamps were anchored. Recorded per source so a later
# multi-session composer knows how precisely two tracks can be aligned:
#   device - the device sent absolute epoch times and they were passed through
#   server - the device sent a local clock and the dispatcher anchored it
TIME_SOURCE_DEVICE = 'device'
TIME_SOURCE_SERVER = 'server'

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
        # Source id -> time_source, not yet written to session_sources.
        self._pending_sources = {}
        self._known_sources = {}
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
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS session_meta (
                key TEXT PRIMARY KEY, value TEXT
            )
        """)
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS session_sources (
                source_id TEXT PRIMARY KEY, time_source TEXT, first_seen_ms REAL
            )
        """)
        self.cursor.executemany(
            "INSERT OR REPLACE INTO session_meta (key, value) VALUES (?, ?)",
            [
                ('schema_version', str(SESSION_SCHEMA_VERSION)),
                ('origin', 'recorded'),
                ('created_at_ms', str(time.time() * 1000.0)),
            ],
        )
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
        self._pending_sources = {}
        self._known_sources = {}
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

    def write(self, event, binary_blob=None, time_source=None):
        """
        Writes an event to the database buffer.

        binary_blob can contain optional bytes, such as JPEG data, for
        efficient BLOB storage. time_source records how the source's
        timestamps were anchored (see TIME_SOURCE_*).
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
            source_id = payload.get('sourceId', 'system')
            if time_source and self._known_sources.get(source_id) != time_source:
                self._known_sources[source_id] = time_source
                self._pending_sources[source_id] = (time_source, evt_time)

            self.buffer.append((
                evt_time,
                source_id,
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
        if not self.conn or not self.cursor:
            return
        if not self.buffer and not self._pending_sources:
            return
        try:
            if self._pending_sources:
                self.cursor.executemany(
                    "INSERT OR REPLACE INTO session_sources "
                    "(source_id, time_source, first_seen_ms) VALUES (?, ?, ?)",
                    [(sid, ts, seen) for sid, (ts, seen) in self._pending_sources.items()],
                )
                self._pending_sources = {}
            if self.buffer:
                self.cursor.executemany(
                    """
                    INSERT INTO session_log (
                        event_time_ms, source_id, distribution, type,
                        payload, binary_data, ingest_ts
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    self.buffer,
                )
                self.buffer = []
            self.conn.commit()
            self.last_flush = time.time()
        except sqlite3.Error as e:
            logger.error("DB Write Error: %s", e)

    def _write_time_bounds(self):
        """Persist the recording's time span so readers don't have to guess it."""
        if not self.conn or not self.cursor:
            return
        try:
            self.cursor.execute(
                "SELECT MIN(event_time_ms), MAX(event_time_ms) FROM session_log "
                "WHERE type = 'DATA_STREAM'"
            )
            row = self.cursor.fetchone()
            if not row or row[0] is None or row[1] is None:
                return
            self.cursor.executemany(
                "INSERT OR REPLACE INTO session_meta (key, value) VALUES (?, ?)",
                [
                    ('session_start_ms', str(float(row[0]))),
                    ('session_end_ms', str(float(row[1]))),
                ],
            )
            self.conn.commit()
        except sqlite3.Error as e:
            logger.error("Failed to write session time bounds: %s", e)

    def stop(self):
        """Stops the current recording session."""
        if not self.state.recording:
            return {'error': 'Not recording'}

        self.write({"type": "SESSION_END", "timestamp": time.time() * 1000})
        self._flush()
        self._write_time_bounds()

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
