"""This module contains the SessionReplayer class."""
import math
import re
import threading
import time
import os
import json
import sqlite3
import base64
import logging
from contextlib import closing
from .config import SESSION_DIR

logger = logging.getLogger(__name__)

# Sanity bounds for recorded timestamps. Anything outside this range is
# treated as corrupt: 2020-01-01 to 2100-01-01 in milliseconds since epoch.
_MIN_VALID_MS = 1_577_836_800_000
_MAX_VALID_MS = 4_102_444_800_000

# Session IDs are produced by the recorder as ``YYYY-MM-DD_HH-MM-SS``,
# optionally followed by ``_<user-supplied-name>``. The whitelist blocks
# path separators, ``..`` traversal and absolute paths before the value
# reaches ``os.path.join``; the realpath containment check below is the
# real defence in depth.
_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._ -]{0,127}$")

# Amount of recorded history replayed right before a new seek position so a
# paused/scrubbing UI immediately shows data instead of an empty widget.
_SEEK_PREROLL_MS = 2000.0


def _read_time_bounds(cur):
    """Return the session's (start_ms, end_ms).

    ``session_meta`` is authoritative because a composed session cannot derive
    its span from the log alone. Older recordings without that table fall back
    to the min/max of the log.
    """
    try:
        cur.execute(
            "SELECT key, value FROM session_meta "
            "WHERE key IN ('session_start_ms', 'session_end_ms')"
        )
        meta = dict(cur.fetchall())
        if 'session_start_ms' in meta and 'session_end_ms' in meta:
            return meta['session_start_ms'], meta['session_end_ms']
    except sqlite3.Error:
        pass  # No session_meta table: pre-schema-1 recording.

    cur.execute(
        "SELECT MIN(event_time_ms), MAX(event_time_ms) FROM session_log "
        "WHERE type = 'DATA_STREAM'"
    )
    res = cur.fetchone()
    return (res[0], res[1]) if res else (None, None)

class SessionReplayer(threading.Thread):  # pylint: disable=too-many-instance-attributes
    """A class to replay recorded sessions."""
    def __init__(self, socketio):
        super().__init__(daemon=True)
        self.socketio = socketio
        self.active_session_path = None
        self.running = False
        self.paused = False
        self.speed = 1.0

        self.session_start_ms = 0
        self.session_duration_ms = 0
        self.current_replay_ms = 0
        self.last_wall_clock = 0

        self.queue_lock = threading.Lock()
        self.command_queue = []

    def load_session(self, session_id):
        """Loads a session for replaying."""
        if not isinstance(session_id, str) or not _SESSION_ID_RE.match(session_id):
            logger.warning("load_session rejected invalid session_id %r", session_id)
            return False, "Invalid session id"

        sessions_root = os.path.realpath(SESSION_DIR)
        candidate = os.path.realpath(os.path.join(sessions_root, session_id, "session.sqlite"))
        # Containment check: the resolved path must live inside SESSION_DIR
        # and its direct parent must be ``<sessions_root>/<session_id>``.
        expected_parent = os.path.realpath(os.path.join(sessions_root, session_id))
        if os.path.dirname(candidate) != expected_parent:
            logger.warning(
                "load_session rejected out-of-root path for %r (resolved=%s)",
                session_id, candidate,
            )
            return False, "Invalid session id"
        path = candidate
        if not os.path.isfile(path):
            return False, "Session file not found"

        self.active_session_path = path

        try:
            with closing(sqlite3.connect(path)) as conn:
                conn.execute("PRAGMA journal_mode=WAL;")
                cur = conn.cursor()
                start_raw, end_raw = _read_time_bounds(cur)
        except sqlite3.Error as e:
            logger.error(
                "Failed to read session metadata from %s: %s", session_id, e)
            return False, "Database error"

        # Defensive: reject NaN/Inf and out-of-range timestamps so a corrupt
        # session file cannot stall the replayer in an infinite seek loop.
        def _clean(v):
            if v is None:
                return None
            try:
                f = float(v)
            except (TypeError, ValueError):
                return None
            if not math.isfinite(f) or f < _MIN_VALID_MS or f > _MAX_VALID_MS:
                return None
            return f

        start_ms = _clean(start_raw)
        end_ms = _clean(end_raw)

        if start_ms is None or end_ms is None:
            logger.warning(
                "Session %s has no valid DATA_STREAM timestamps (raw=%s..%s)",
                session_id, start_raw, end_raw,
            )
            return False, "Session contains no valid data"
        if end_ms < start_ms:
            logger.warning(
                "Session %s timestamps inverted (start=%s, end=%s); aborting load.",
                session_id, start_ms, end_ms,
            )
            return False, "Session timestamps inconsistent"

        self.session_start_ms = start_ms
        self.session_duration_ms = end_ms - start_ms


        self.current_replay_ms = 0
        self.paused = True
        self.running = True
        return True, "Loaded"

    def control(self, action, value=None):
        """Controls the replayer."""
        with self.queue_lock:
            self.command_queue.append((action, value))

    def _emit_reset(self, time_ms):
        """Tell UIs to drop buffered replay data before a position jump.

        Stop, seek and the automatic rewind on play move the cursor
        discontinuously. Without an explicit reset the widgets would splice
        the new segment onto stale samples of the old position.
        """
        self.socketio.emit(
            'replay_reset',
            {'time_ms': time_ms, 'duration': self.session_duration_ms},
            room='ui_clients',
        )

    def _emit_range(self, cursor, rel_start, rel_end):
        """Emit recorded events of the session window ``[rel_start, rel_end)``.

        Recordings are stored with absolute epoch timestamps, so playback first
        makes them session-relative and then shifts them onto the wall clock:
        ``rel_end`` maps to "now". A replay therefore behaves like a source that
        is producing right now and can be charted next to live signals, while
        the recording itself stays independent of when it was made.
        """
        offset = (time.time() * 1000.0 - rel_end) - self.session_start_ms

        query = """
            SELECT payload, binary_data FROM session_log
            WHERE event_time_ms >= ? AND event_time_ms < ?
            ORDER BY event_time_ms ASC, seq ASC
        """
        cursor.execute(
            query,
            (self.session_start_ms + rel_start, self.session_start_ms + rel_end),
        )

        for row in cursor.fetchall():
            payload_str = row[0]
            binary_blob = row[1]

            event_data = json.loads(payload_str)

            if binary_blob:
                try:
                    b64_str = base64.b64encode(binary_blob).decode('utf-8')
                    event_data['payload']['image_b64'] = f"data:image/jpeg;base64,{b64_str}"
                except (TypeError, ValueError) as e:
                    logger.error("Replay Image Error: %s", e)

            if event_data.get('type') != 'DATA_STREAM':
                continue

            replayed_payload = event_data['payload']

            for key in ('startTime', 'endTime', 'timestamp'):
                if key in replayed_payload:
                    replayed_payload[key] = float(replayed_payload[key]) + offset
            if isinstance(replayed_payload.get('timestamps'), list):
                replayed_payload['timestamps'] = [
                    float(t) + offset for t in replayed_payload['timestamps']
                ]

            original_source_id = replayed_payload.get('sourceId')
            if original_source_id:
                replayed_payload['sourceId'] = f"rec_{original_source_id}"
                replayed_payload['originalSourceId'] = original_source_id
            # Carried inside the payload (not the log wrapper) so the UI can
            # keep replay samples out of live buffers.
            replayed_payload['_is_replay'] = True

            self.socketio.emit('data_stream', replayed_payload, room='ui_clients')

    def run(self):  # pylint: disable=too-many-locals,too-many-branches,too-many-statements
        """The main loop of the replayer."""
        conn = None
        cursor = None

        while True:
            if not self.running or not self.active_session_path:
                if conn is not None:
                    conn.close()
                    conn = None
                    cursor = None
                time.sleep(0.1)
                continue

            if conn is None:
                try:
                    conn = sqlite3.connect(
                        self.active_session_path, check_same_thread=False)
                    conn.execute("PRAGMA journal_mode=WAL;")
                    cursor = conn.cursor()
                except sqlite3.Error as e:
                    logger.error("Replayer failed to connect to DB: %s", e)
                    self.active_session_path = None # Stop trying
                    continue


            with self.queue_lock:
                while self.command_queue:
                    cmd, val = self.command_queue.pop(0)
                    if cmd == 'unload':
                        self.running = False
                        self.active_session_path = None
                        self.current_replay_ms = 0
                        self.session_duration_ms = 0
                        self.socketio.emit(
                            'replay_status',
                            {'state': 'stopped'},
                            room='ui_clients',
                        )
                    elif cmd == 'stop':
                        self.paused = True
                        self.current_replay_ms = 0
                        self.last_wall_clock = time.time()
                        self._emit_reset(0)
                        self.socketio.emit(
                            'replay_progress',
                            {'time_ms': 0, 'duration': self.session_duration_ms},
                            room='ui_clients')
                        self.socketio.emit(
                            'replay_status', {'state': 'stopped'}, room='ui_clients')

                    elif cmd == 'pause':
                        self.paused = True
                        self.socketio.emit(
                            'replay_status',
                            {'state': 'paused'},
                            room='ui_clients',
                        )
                    elif cmd == 'play':
                        # Restart from the top when the cursor already sits at
                        # the end, otherwise play would be a no-op forever.
                        if (self.session_duration_ms > 0
                                and self.current_replay_ms >= self.session_duration_ms):
                            self.current_replay_ms = 0
                            self._emit_reset(0)
                            self.socketio.emit(
                                'replay_progress',
                                {'time_ms': 0, 'duration': self.session_duration_ms},
                                room='ui_clients',
                            )
                        self.paused = False
                        self.last_wall_clock = time.time()
                        self.socketio.emit(
                            'replay_status',
                            {'state': 'playing'},
                            room='ui_clients',
                        )
                    elif cmd == 'seek':
                        try:
                            seek_ms = float(val) if val is not None else 0.0
                        except (TypeError, ValueError):
                            seek_ms = 0.0
                        if not math.isfinite(seek_ms):
                            seek_ms = 0.0
                        # Clamp to the session bounds so a stray value can't
                        # park the replayer outside the valid range.
                        seek_ms = max(0.0, min(seek_ms, float(self.session_duration_ms)))
                        self.current_replay_ms = seek_ms
                        self.last_wall_clock = time.time()
                        self._emit_reset(seek_ms)
                        try:
                            preroll_start = max(0.0, seek_ms - _SEEK_PREROLL_MS)
                            self._emit_range(cursor, preroll_start, seek_ms)
                        except sqlite3.Error as e:
                            logger.error("Replayer seek preroll failed: %s", e)
                        self.socketio.emit(
                            'replay_progress',
                            {'time_ms': self.current_replay_ms,
                                'duration': self.session_duration_ms},
                            room='ui_clients',
                        )

            if not self.running or not self.active_session_path:
                if conn:
                    conn.close()
                conn = None
                continue

            if self.paused:
                time.sleep(0.1)
                continue

            # --- Check for end of replay ---
            if self.session_duration_ms > 0 and self.current_replay_ms >= self.session_duration_ms:
                self.paused = True
                self.current_replay_ms = self.session_duration_ms # Clamp to end
                self.socketio.emit(
                    'replay_status', {'state': 'stopped'}, room='ui_clients')
                self.socketio.emit(
                    'replay_progress',
                    {'time_ms': self.current_replay_ms,
                        'duration': self.session_duration_ms},
                    room='ui_clients'
                )
                continue


            now = time.time()
            dt = (now - self.last_wall_clock) * 1000.0 * self.speed
            self.last_wall_clock = now

            next_replay_ms = self.current_replay_ms + dt

            try:
                assert cursor is not None  # guaranteed: cursor is set when conn is not None
                self._emit_range(cursor, self.current_replay_ms, next_replay_ms)

                self.current_replay_ms = next_replay_ms
                self.socketio.emit('replay_progress', {'time_ms': self.current_replay_ms,
                                     'duration': self.session_duration_ms}, room='ui_clients')
            except sqlite3.Error as e:
                logger.error("Replayer DB read error: %s", e)
                self.paused = True # Stop on error

            time.sleep(0.01)
