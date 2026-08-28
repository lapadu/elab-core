"""Integration tests for session recording and replay (recorder.py, sockets.py session events).

These tests exercise the complete session recording lifecycle:
- session_start / session_stop
- Data is written to SQLite during recording
- get_sessions returns the recorded session
- replay_load loads a session
- delete_session with path traversal checks
"""
import os
import time
import copy
import sqlite3
import pytest

from .conftest import VALID_MANIFEST


class TestSessionRecording:
    """Tests for session_start / session_stop / data recording."""

    def test_session_start_creates_db(self, client, state, recorder, session_dir):
        """session_start should create a SQLite database."""
        client.emit('session_start', {'session_id': 'test_session_001'})
        received = client.get_received()
        result_events = [r for r in received if r['name'] == 'session_start_result']
        assert len(result_events) == 1
        result = result_events[0]['args'][0]
        assert result['status'] == 'started'
        assert 'test_session_001' in result['session_id']

        # The actual directory name is prefixed with a timestamp
        actual_session_id = result['session_id']
        db_path = session_dir / actual_session_id / 'session.sqlite'
        assert db_path.exists()

        # Stop recording
        client.emit('session_stop', {})
        received = client.get_received()
        stop_events = [r for r in received if r['name'] == 'session_stop_result']
        assert len(stop_events) == 1
        assert stop_events[0]['args'][0]['status'] == 'stopped'

    def test_data_stream_recorded_to_sqlite(self, client, state, recorder, session_dir):
        """data_stream events should be written to the session database."""
        from elab_server.app import app, socketio

        # Register provider
        provider_client = socketio.test_client(app)
        provider_client.emit('register_provider', copy.deepcopy(VALID_MANIFEST))

        # Register UI
        client.emit('register_client', {'client_type': 'ui'})
        client.get_received()

        # Assign the task to a slot (required for recording)
        client.emit('task_assigned', {'slot': 0, 'taskId': 'test_task_1'})

        # Start session
        client.emit('session_start', {'session_id': 'test_data_rec'})
        received = client.get_received()
        result_events = [r for r in received if r['name'] == 'session_start_result']
        actual_session_id = result_events[0]['args'][0]['session_id']

        # Send data
        for i in range(5):
            provider_client.emit('data_stream', {
                'sourceId': 'test_task_1',
                'value': float(i),
                'timestamp': time.time() * 1000 + i,
            })

        # Give recorder time to flush
        time.sleep(0.8)

        # Stop session
        client.emit('session_stop', {})
        client.get_received()

        # Check SQLite
        db_path = session_dir / actual_session_id / 'session.sqlite'
        assert db_path.exists()
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM session_log WHERE type='DATA_STREAM'")
        count = cursor.fetchone()[0]
        assert count >= 5
        conn.close()

        provider_client.disconnect()

    def test_session_metadata_and_time_source_recorded(
        self, client, state, recorder, session_dir
    ):
        """A recording must persist its own time span and per-source time quality."""
        from elab_server.app import app, socketio

        provider_client = socketio.test_client(app)
        provider_client.emit('register_provider', copy.deepcopy(VALID_MANIFEST))

        client.emit('register_client', {'client_type': 'ui'})
        client.get_received()
        client.emit('task_assigned', {'slot': 0, 'taskId': 'test_task_1'})

        client.emit('session_start', {'session_id': 'test_meta'})
        received = client.get_received()
        actual_session_id = [
            r for r in received if r['name'] == 'session_start_result'
        ][0]['args'][0]['session_id']

        # Device-local clock (millis()) -> the dispatcher has to anchor it.
        for i in range(5):
            provider_client.emit('data_stream', {
                'sourceId': 'test_task_1',
                'value': float(i),
                'timestamp': 1000.0 + i,
            })

        time.sleep(0.8)
        client.emit('session_stop', {})
        client.get_received()

        conn = sqlite3.connect(str(session_dir / actual_session_id / 'session.sqlite'))
        cursor = conn.cursor()

        cursor.execute("SELECT key, value FROM session_meta")
        meta = dict(cursor.fetchall())
        assert meta['origin'] == 'recorded'
        assert meta['schema_version'] == '1'
        start_ms = float(meta['session_start_ms'])
        end_ms = float(meta['session_end_ms'])
        assert end_ms >= start_ms

        cursor.execute(
            "SELECT MIN(event_time_ms), MAX(event_time_ms) FROM session_log "
            "WHERE type = 'DATA_STREAM'"
        )
        log_min, log_max = cursor.fetchone()
        assert start_ms == log_min
        assert end_ms == log_max

        cursor.execute(
            "SELECT time_source FROM session_sources WHERE source_id = 'test_task_1'")
        assert cursor.fetchone()[0] == 'server'
        conn.close()

        provider_client.disconnect()

    def test_session_stop_without_start(self, client, state, session_dir):
        """session_stop when no session is active should return error."""
        client.emit('session_stop', {})
        received = client.get_received()
        stop_events = [r for r in received if r['name'] == 'session_stop_result']
        assert len(stop_events) == 1
        assert 'error' in stop_events[0]['args'][0]


class TestSessionManagement:
    """Tests for get_sessions, delete_session."""

    def _create_session(self, session_dir, name):
        """Helper: create a fake session directory with a SQLite file."""
        session_path = session_dir / name
        session_path.mkdir(parents=True, exist_ok=True)
        db_path = session_path / 'session.sqlite'
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE IF NOT EXISTS session_log (id INTEGER PRIMARY KEY)")
        conn.close()

    def test_get_sessions_returns_list(self, client, state, session_dir):
        """get_sessions should return existing sessions sorted descending."""
        self._create_session(session_dir, '2025-01-01_10-00-00')
        self._create_session(session_dir, '2025-01-02_10-00-00')
        self._create_session(session_dir, '2025-01-03_10-00-00')

        client.emit('get_sessions')
        received = client.get_received()
        list_events = [r for r in received if r['name'] == 'session_list']
        assert len(list_events) == 1
        sessions = list_events[0]['args'][0]
        assert sessions == ['2025-01-03_10-00-00', '2025-01-02_10-00-00', '2025-01-01_10-00-00']

    def test_get_sessions_empty(self, client, state, session_dir):
        """get_sessions on empty directory returns empty list."""
        client.emit('get_sessions')
        received = client.get_received()
        list_events = [r for r in received if r['name'] == 'session_list']
        assert len(list_events) == 1
        assert list_events[0]['args'][0] == []

    def test_delete_session_removes_directory(self, client, state, session_dir):
        """delete_session should remove the session directory."""
        self._create_session(session_dir, 'to_delete')
        assert (session_dir / 'to_delete').exists()

        client.emit('delete_session', {'session_id': 'to_delete'})
        assert not (session_dir / 'to_delete').exists()

    def test_delete_session_path_traversal_blocked(self, client, state, session_dir):
        """Path traversal attempts should be blocked."""
        self._create_session(session_dir, 'safe_session')

        client.emit('delete_session', {'session_id': '../etc/passwd'})
        # Should NOT delete anything
        assert (session_dir / 'safe_session').exists()

    def test_delete_session_backslash_traversal_blocked(self, client, state, session_dir):
        """Backslash path traversal should also be blocked."""
        self._create_session(session_dir, 'safe_session')

        client.emit('delete_session', {'session_id': '..\\windows\\system32'})
        assert (session_dir / 'safe_session').exists()

    def test_delete_nonexistent_session(self, client, state, session_dir):
        """Deleting a non-existent session should be a no-op."""
        # Should not raise
        client.emit('delete_session', {'session_id': 'does_not_exist'})


class TestReplay:
    """Tests for replay_load and replay_action."""

    def _create_session_with_data(self, session_dir, name):
        """Helper: create a session with some DATA_STREAM entries."""
        session_path = session_dir / name
        session_path.mkdir(parents=True, exist_ok=True)
        db_path = session_path / 'session.sqlite'
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS session_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_time_ms REAL,
                type TEXT,
                source_id TEXT,
                payload TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS manifests (
                task_id TEXT PRIMARY KEY,
                manifest TEXT
            )
        """)
        # Insert some test data
        import json
        base_time = time.time() * 1000
        for i in range(10):
            conn.execute(
                "INSERT INTO session_log (event_time_ms, type, source_id, payload) VALUES (?, ?, ?, ?)",
                (base_time + i * 100, 'DATA_STREAM', 'test_task_1',
                 json.dumps({'value': float(i)}))
            )
        # Insert a manifest
        manifest = copy.deepcopy(VALID_MANIFEST)
        conn.execute(
            "INSERT INTO manifests (task_id, manifest) VALUES (?, ?)",
            ('test_task_1', json.dumps(manifest))
        )
        conn.commit()
        conn.close()

    def test_replay_load_success(self, client, state, session_dir):
        """replay_load should return success and duration for a valid session."""
        self._create_session_with_data(session_dir, 'replay_test')

        client.emit('replay_load', {'session_id': 'replay_test'})
        received = client.get_received()
        load_events = [r for r in received if r['name'] == 'replay_loaded']
        assert len(load_events) == 1
        data = load_events[0]['args'][0]
        assert data['success'] is True
        assert data['session_id'] == 'replay_test'
        assert data['duration'] > 0

    def test_replay_load_accepts_spaces_in_session_id(self, client, state, session_dir):
        """replay_load should accept recorder-created names containing spaces."""
        session_id = 'replay test'
        self._create_session_with_data(session_dir, session_id)

        client.emit('replay_load', {'session_id': session_id})
        received = client.get_received()
        load_events = [r for r in received if r['name'] == 'replay_loaded']
        assert len(load_events) == 1
        data = load_events[0]['args'][0]
        assert data['success'] is True
        assert data['session_id'] == session_id

    def test_replay_load_nonexistent(self, client, state, session_dir):
        """replay_load for a nonexistent session should return failure."""
        client.emit('replay_load', {'session_id': 'does_not_exist'})
        received = client.get_received()
        load_events = [r for r in received if r['name'] == 'replay_loaded']
        assert len(load_events) == 1
        assert load_events[0]['args'][0]['success'] is False

    def test_get_recorded_providers(self, client, state, session_dir):
        """get_recorded_providers should return modified manifests for replay."""
        self._create_session_with_data(session_dir, 'rec_prov_test')

        client.emit('get_recorded_providers', {'session_id': 'rec_prov_test'})
        received = client.get_received()
        rp_events = [r for r in received if r['name'] == 'recorded_providers']
        assert len(rp_events) == 1
        providers = rp_events[0]['args'][0]['providers']
        assert len(providers) >= 1
        # Check the recorded prefix
        assert providers[0]['id'].startswith('rec_')
        assert providers[0]['is_recorded'] is True
        # Tasks should also have rec_ prefix
        task = providers[0]['tasks'][0]
        assert task['id'].startswith('rec_')
        assert task['is_recorded'] is True
