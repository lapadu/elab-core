"""Integration test configuration.

Provides a Flask-SocketIO test client connected to a fully wired server
instance (same as ``python server.py -d``). The test client communicates
over in-process queues – no real socket or port needed.
"""

import os
import sys
import time
import json
import pytest
import sqlite3
import threading

# Ensure the repo root is importable.
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

# Force dispatcher-only mode for tests (no frontend serving).
sys.argv = ["server", "-d"]


@pytest.fixture(scope="session")
def app_context():
    """Create a fully wired Flask-SocketIO app context once per test session."""
    from elab_server.app import app, socketio
    from elab_server.state import SystemState
    from elab_server.recorder import SessionRecorder
    from elab_server.replayer import SessionReplayer
    from elab_server.process_manager import ClientProcessManager
    from elab_server.sockets import register_socket_handlers

    state = SystemState(socketio)
    recorder = SessionRecorder(state, socketio)
    replayer = SessionReplayer(socketio)
    client_manager = ClientProcessManager()

    register_socket_handlers(socketio, state, recorder, replayer, client_manager)

    return {
        "app": app,
        "socketio": socketio,
        "state": state,
        "recorder": recorder,
        "replayer": replayer,
        "client_manager": client_manager,
    }


@pytest.fixture()
def client(app_context):
    """A fresh Socket.IO test client for each test.

    Uses Flask-SocketIO's built-in test_client which communicates
    in-process (no network I/O). Automatically disconnects on teardown.
    """
    socketio = app_context["socketio"]
    app = app_context["app"]
    test_client = socketio.test_client(app)
    yield test_client
    if test_client.is_connected():
        test_client.disconnect()


@pytest.fixture()
def state(app_context):
    """Expose the SystemState and reset it between tests."""
    s = app_context["state"]
    # Clean slate for every test
    with s.atomic_update():
        s.providers.clear()
        s.clients.clear()
        s.active_tasks_by_slot.clear()
        s.decoders.clear()
        s._provider_sid_index.clear()
    s.recording = False
    s.current_session_id = None
    yield s


@pytest.fixture()
def recorder(app_context):
    """Expose the SessionRecorder."""
    return app_context["recorder"]


@pytest.fixture()
def session_dir(tmp_path, monkeypatch):
    """Override the session directory with a temp folder."""
    import elab_server.sockets as sockets_mod
    import elab_server.recorder as recorder_mod
    import elab_server.replayer as replayer_mod
    import elab_server.config as config_mod

    monkeypatch.setattr(sockets_mod, "SESSION_DIR", str(tmp_path))
    monkeypatch.setattr(recorder_mod, "SESSION_DIR", str(tmp_path))
    monkeypatch.setattr(replayer_mod, "SESSION_DIR", str(tmp_path))
    monkeypatch.setattr(config_mod, "SESSION_DIR", str(tmp_path))
    return tmp_path


# --- Helper: a valid manifest fixture ---
VALID_MANIFEST = {
    "id": "test_provider",
    "name": "Integration Test Provider",
    "category": "HARDWARE",
    "version": "1.0.0",
    "capabilities": ["stream"],
    "tasks": [
        {
            "id": "test_task_1",
            "name": "Test Sensor",
            "type": "SENSOR",
            "ui": {"mode": "generic"},
            "config": {"unit": "V", "timeWindow": 5},
        }
    ],
}
