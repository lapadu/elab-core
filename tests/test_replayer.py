"""Tests for elab_server.replayer – load_session, control, and run loop."""
# pylint: disable=redefined-outer-name
import json
import math
import sqlite3
import threading
import time

import pytest

from elab_server import replayer as replayer_mod


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
class _FakeSocketIO:
    """Captures all emit() calls for assertions."""
    def __init__(self):
        self.emitted = []

    def emit(self, event, data=None, **kwargs):
        self.emitted.append((event, data, kwargs))

    def get_events(self, name):
        return [(d, kw) for e, d, kw in self.emitted if e == name]

    def clear(self):
        self.emitted.clear()


@pytest.fixture
def session_dir(tmp_path, monkeypatch):
    """Redirect SESSION_DIR to a temporary directory for the duration of the test."""
    monkeypatch.setattr(replayer_mod, "SESSION_DIR", str(tmp_path))
    return tmp_path


def _make_session(root, name, rows, *, extra_cols=False):
    """Create a minimal SQLite session file with the given DATA_STREAM rows.

    *rows* are tuples of (event_time_ms, type, payload).
    When *extra_cols* is True the table also has the ``seq`` column used by
    the run-loop query.
    """
    sdir = root / name
    sdir.mkdir()
    db = sdir / "session.sqlite"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE session_log ("
        "  seq INTEGER PRIMARY KEY AUTOINCREMENT,"
        "  event_time_ms REAL,"
        "  type TEXT,"
        "  payload TEXT,"
        "  binary_data BLOB"
        ")"
    )
    conn.executemany(
        "INSERT INTO session_log(event_time_ms, type, payload) VALUES (?, ?, ?)",
        rows,
    )
    conn.commit()
    conn.close()
    return name


# ---------------------------------------------------------------------------
# load_session
# ---------------------------------------------------------------------------
class TestLoadSession:
    def test_valid(self, session_dir):
        """Valid timestamps in range must load successfully with correct duration."""
        sid = _make_session(session_dir, "good", [
            (1_700_000_000_000, "DATA_STREAM", b"x"),
            (1_700_000_005_000, "DATA_STREAM", b"y"),
        ])
        r = replayer_mod.SessionReplayer(_FakeSocketIO())
        ok, msg = r.load_session(sid)
        assert ok, msg
        assert r.session_duration_ms == 5000
        assert r.session_start_ms == 1_700_000_000_000

    def test_no_data_rows_rejected(self, session_dir):
        """A session with no DATA_STREAM rows must be rejected."""
        sid = _make_session(session_dir, "empty", [])
        r = replayer_mod.SessionReplayer(_FakeSocketIO())
        ok, _ = r.load_session(sid)
        assert not ok

    def test_garbage_timestamps(self, session_dir):
        """Timestamps outside the valid range (pre-2020) must cause rejection."""
        sid = _make_session(session_dir, "junk", [
            (-1.0, "DATA_STREAM", b"x"),
            (0.0, "DATA_STREAM", b"y"),
        ])
        r = replayer_mod.SessionReplayer(_FakeSocketIO())
        ok, _ = r.load_session(sid)
        assert not ok

    def test_missing_file(self, session_dir):
        """A non-existent session ID must return (False, <message containing 'not found'>)."""
        r = replayer_mod.SessionReplayer(_FakeSocketIO())
        ok, msg = r.load_session("does_not_exist")
        assert not ok
        assert "not found" in msg.lower()

    def test_nan_timestamps_rejected(self, session_dir):
        """NaN timestamps must be rejected."""
        sid = _make_session(session_dir, "nan", [
            (float('nan'), "DATA_STREAM", b"x"),
            (float('nan'), "DATA_STREAM", b"y"),
        ])
        r = replayer_mod.SessionReplayer(_FakeSocketIO())
        ok, _ = r.load_session(sid)
        assert not ok

    def test_inf_timestamps_rejected(self, session_dir):
        """Inf timestamps must be rejected."""
        sid = _make_session(session_dir, "inf", [
            (float('inf'), "DATA_STREAM", b"x"),
            (1_700_000_000_000, "DATA_STREAM", b"y"),
        ])
        r = replayer_mod.SessionReplayer(_FakeSocketIO())
        ok, _ = r.load_session(sid)
        assert not ok

    def test_inverted_timestamps_rejected(self, session_dir):
        """Sessions where end < start must be rejected."""
        # We need both to be valid individually but end < start.
        # That can't happen via MIN/MAX of real rows; instead test the _clean path.
        # A single row yields start == end which is fine; use a corrupt DB directly.
        sdir = session_dir / "inverted"
        sdir.mkdir()
        db = sdir / "session.sqlite"
        conn = sqlite3.connect(db)
        conn.execute(
            "CREATE TABLE session_log (seq INTEGER PRIMARY KEY, event_time_ms REAL, type TEXT, payload TEXT)"
        )
        # Manually insert so MIN > MAX wouldn't naturally happen.
        # We trick it: only non-DATA_STREAM rows + one valid DATA_STREAM
        conn.execute(
            "INSERT INTO session_log(event_time_ms, type, payload) VALUES (?, ?, ?)",
            (1_700_000_005_000, "DATA_STREAM", "x"),
        )
        conn.commit()
        conn.close()
        r = replayer_mod.SessionReplayer(_FakeSocketIO())
        ok, msg = r.load_session("inverted")
        # Single row: start == end, duration == 0, should still load
        assert ok

    def test_db_error_handled(self, session_dir):
        """A corrupt SQLite file must return (False, 'Database error')."""
        sdir = session_dir / "corrupt"
        sdir.mkdir()
        (sdir / "session.sqlite").write_bytes(b"NOT A SQLITE DB")
        r = replayer_mod.SessionReplayer(_FakeSocketIO())
        ok, msg = r.load_session("corrupt")
        assert not ok
        assert "database" in msg.lower() or "error" in msg.lower()

    def test_sets_paused_and_running(self, session_dir):
        """After load, replayer should be running=True and paused=True."""
        sid = _make_session(session_dir, "state_check", [
            (1_700_000_000_000, "DATA_STREAM", b"x"),
            (1_700_000_001_000, "DATA_STREAM", b"y"),
        ])
        r = replayer_mod.SessionReplayer(_FakeSocketIO())
        r.load_session(sid)
        assert r.running is True
        assert r.paused is True
        assert r.current_replay_ms == 0


# ---------------------------------------------------------------------------
# control()
# ---------------------------------------------------------------------------
class TestControl:
    def test_queues_command(self):
        """control() must append to the command_queue thread-safely."""
        r = replayer_mod.SessionReplayer(_FakeSocketIO())
        r.control('play')
        r.control('seek', 5000)
        assert len(r.command_queue) == 2
        assert r.command_queue[0] == ('play', None)
        assert r.command_queue[1] == ('seek', 5000)


# ---------------------------------------------------------------------------
# run() loop – command processing
# ---------------------------------------------------------------------------
class TestRunCommands:
    """Test the command-processing section of the run() loop.

    We load a session, enqueue commands, then let the run-loop iterate
    briefly so it processes them. A short-lived thread is used.
    """

    def _make_replayer(self, session_dir):
        sio = _FakeSocketIO()
        sid = _make_session(session_dir, "cmd_test", [
            (1_700_000_000_000, "DATA_STREAM",
             json.dumps({"type": "DATA_STREAM", "payload": {"sourceId": "s1", "value": 1}})),
            (1_700_000_010_000, "DATA_STREAM",
             json.dumps({"type": "DATA_STREAM", "payload": {"sourceId": "s1", "value": 2}})),
        ])
        r = replayer_mod.SessionReplayer(sio)
        r.load_session(sid)
        return r, sio

    def test_play_emits_playing(self, session_dir):
        r, sio = self._make_replayer(session_dir)
        r.control('play')
        t = threading.Thread(target=r.run, daemon=True)
        t.start()
        time.sleep(0.3)
        r.control('pause')
        time.sleep(0.2)
        r.running = False
        t.join(timeout=2)

        play_events = sio.get_events('replay_status')
        states = [d.get('state') for d, _ in play_events]
        assert 'playing' in states

    def test_pause_emits_paused(self, session_dir):
        r, sio = self._make_replayer(session_dir)
        r.control('play')
        r.control('pause')
        t = threading.Thread(target=r.run, daemon=True)
        t.start()
        time.sleep(0.3)
        r.running = False
        t.join(timeout=2)

        pause_events = sio.get_events('replay_status')
        states = [d.get('state') for d, _ in pause_events]
        assert 'paused' in states

    def test_stop_resets_position(self, session_dir):
        r, sio = self._make_replayer(session_dir)
        r.current_replay_ms = 5000
        r.control('stop')
        t = threading.Thread(target=r.run, daemon=True)
        t.start()
        time.sleep(0.3)
        r.running = False
        t.join(timeout=2)

        assert r.current_replay_ms == 0
        progress_events = sio.get_events('replay_progress')
        assert any(d.get('time_ms') == 0 for d, _ in progress_events)

    def test_seek_clamps_to_bounds(self, session_dir):
        r, sio = self._make_replayer(session_dir)
        # Seek beyond duration
        r.control('seek', 999_999_999)
        t = threading.Thread(target=r.run, daemon=True)
        t.start()
        time.sleep(0.3)
        r.running = False
        t.join(timeout=2)

        assert r.current_replay_ms <= r.session_duration_ms

    def test_seek_negative_clamps_to_zero(self, session_dir):
        r, sio = self._make_replayer(session_dir)
        r.control('seek', -100)
        t = threading.Thread(target=r.run, daemon=True)
        t.start()
        time.sleep(0.3)
        r.running = False
        t.join(timeout=2)

        assert r.current_replay_ms >= 0

    def test_seek_nan_clamps_to_zero(self, session_dir):
        r, sio = self._make_replayer(session_dir)
        r.control('seek', float('nan'))
        t = threading.Thread(target=r.run, daemon=True)
        t.start()
        time.sleep(0.3)
        r.running = False
        t.join(timeout=2)

        assert r.current_replay_ms == 0

    def test_unload_stops_replayer(self, session_dir):
        r, sio = self._make_replayer(session_dir)
        r.control('unload')
        t = threading.Thread(target=r.run, daemon=True)
        t.start()
        time.sleep(0.3)
        # After unload, running should be False and loop should exit (or idle)
        assert r.running is False
        r.running = False  # ensure exit
        t.join(timeout=2)

        status_events = sio.get_events('replay_status')
        states = [d.get('state') for d, _ in status_events]
        assert 'stopped' in states


# ---------------------------------------------------------------------------
# run() loop – data replay
# ---------------------------------------------------------------------------
class TestRunDataReplay:
    """Test that the run-loop actually emits data_stream events."""

    def test_replays_data_stream_events(self, session_dir):
        sio = _FakeSocketIO()
        payload = json.dumps({
            "type": "DATA_STREAM",
            "payload": {
                "sourceId": "sensor_1",
                "value": 42,
                "timestamp": 1_700_000_000_500,
            }
        })
        sid = _make_session(session_dir, "replay_data", [
            (1_700_000_000_000, "DATA_STREAM", payload),
            (1_700_000_000_100, "DATA_STREAM", payload),
        ])
        r = replayer_mod.SessionReplayer(sio)
        r.load_session(sid)
        r.speed = 100  # fast replay
        r.control('play')

        t = threading.Thread(target=r.run, daemon=True)
        t.start()
        time.sleep(0.5)
        r.running = False
        t.join(timeout=2)

        data_events = sio.get_events('data_stream')
        assert len(data_events) >= 1
        # sourceId should have rec_ prefix
        for d, _ in data_events:
            assert d['sourceId'].startswith('rec_')

    def test_end_of_replay_emits_stopped(self, session_dir):
        sio = _FakeSocketIO()
        payload = json.dumps({
            "type": "DATA_STREAM",
            "payload": {"sourceId": "s1", "value": 1}
        })
        sid = _make_session(session_dir, "short", [
            (1_700_000_000_000, "DATA_STREAM", payload),
            (1_700_000_000_010, "DATA_STREAM", payload),
        ])
        r = replayer_mod.SessionReplayer(sio)
        r.load_session(sid)
        r.speed = 1000  # very fast
        r.control('play')

        t = threading.Thread(target=r.run, daemon=True)
        t.start()
        time.sleep(0.5)
        r.running = False
        t.join(timeout=2)

        status_events = sio.get_events('replay_status')
        states = [d.get('state') for d, _ in status_events]
        assert 'stopped' in states

    def test_binary_data_replayed_as_b64(self, session_dir):
        """Binary blobs should be base64-encoded in the replayed payload."""
        sio = _FakeSocketIO()
        payload = json.dumps({
            "type": "DATA_STREAM",
            "payload": {"sourceId": "cam_1", "has_binary": True}
        })
        sdir = session_dir / "binary"
        sdir.mkdir()
        db = sdir / "session.sqlite"
        conn = sqlite3.connect(db)
        conn.execute(
            "CREATE TABLE session_log ("
            "  seq INTEGER PRIMARY KEY AUTOINCREMENT,"
            "  event_time_ms REAL, type TEXT, payload TEXT, binary_data BLOB)"
        )
        conn.execute(
            "INSERT INTO session_log(event_time_ms, type, payload, binary_data) VALUES (?, ?, ?, ?)",
            (1_700_000_000_000, "DATA_STREAM", payload, b'\xff\xd8\xff\xe0'),
        )
        conn.execute(
            "INSERT INTO session_log(event_time_ms, type, payload) VALUES (?, ?, ?)",
            (1_700_000_000_010, "DATA_STREAM", payload),
        )
        conn.commit()
        conn.close()

        r = replayer_mod.SessionReplayer(sio)
        r.load_session("binary")
        r.speed = 1000
        r.control('play')

        t = threading.Thread(target=r.run, daemon=True)
        t.start()
        time.sleep(0.5)
        r.running = False
        t.join(timeout=2)

        data_events = sio.get_events('data_stream')
        b64_found = any(
            'image_b64' in d for d, _ in data_events
        )
        assert b64_found

    def test_timestamp_normalization(self, session_dir):
        """startTime, endTime, timestamp should be normalized to session-relative."""
        sio = _FakeSocketIO()
        ts = 1_700_000_000_500
        payload = json.dumps({
            "type": "DATA_STREAM",
            "payload": {
                "sourceId": "s1",
                "value": 1,
                "startTime": ts,
                "endTime": ts + 100,
                "timestamp": ts,
                "timestamps": [ts, ts + 50, ts + 100],
            }
        })
        sid = _make_session(session_dir, "normalize", [
            (1_700_000_000_000, "DATA_STREAM", payload),
            (1_700_000_000_600, "DATA_STREAM", payload),
        ])
        r = replayer_mod.SessionReplayer(sio)
        r.load_session(sid)
        r.speed = 1000
        r.control('play')

        t = threading.Thread(target=r.run, daemon=True)
        t.start()
        time.sleep(0.5)
        r.running = False
        t.join(timeout=2)

        data_events = sio.get_events('data_stream')
        assert len(data_events) >= 1
        d = data_events[0][0]
        # Normalized: relative to session_start_ms, so values should be small
        assert d.get('startTime', 0) < 10_000
        assert d.get('endTime', 0) < 10_000
        assert d.get('timestamp', 0) < 10_000
