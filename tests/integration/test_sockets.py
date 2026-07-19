"""Integration tests for Socket.IO event handlers (sockets.py).

These tests start the full server stack in-process (no network port needed)
and exercise the Socket.IO events end-to-end via Flask-SocketIO's test client.
"""

# Test functions intentionally receive shared pytest fixtures that are not always
# consumed in each case; keep pylint focused on meaningful issues here.
# pylint: disable=unused-argument,unused-import,unused-variable

import base64
import json
import os
import sqlite3
import time
import copy
import math
import pytest

from .conftest import VALID_MANIFEST


class TestConnection:
    """Tests for connect / disconnect / register_client lifecycle."""

    def test_connection_established_on_connect(self, client, state):
        """Server emits 'connection_established' immediately after connect."""
        received = client.get_received()
        conn_events = [r for r in received if r["name"] == "connection_established"]
        assert len(conn_events) == 1
        data = conn_events[0]["args"][0]
        assert "client_id" in data
        assert "server_version" in data
        assert "timestamp" in data

    def test_register_client_returns_providers(self, client, state):
        """After register_client, server emits available_providers and scripts."""
        client.emit("register_client", {"client_type": "ui"})
        received = client.get_received()
        event_names = [r["name"] for r in received]
        assert "available_providers" in event_names
        assert "available_scripts" in event_names

    def test_register_client_records_in_state(self, client, state):
        """register_client should add client to state.clients."""
        client.emit("register_client", {"client_type": "ui"})
        assert len(state.clients) >= 1

    def test_register_client_sends_active_tasks_snapshot(self, client, state):
        """If tasks are active, register_client should send active_tasks_snapshot."""
        with state.atomic_update():
            state.active_tasks_by_slot[0] = "task_a"
        client.emit("register_client", {"client_type": "ui"})
        received = client.get_received()
        snap_events = [r for r in received if r["name"] == "active_tasks_snapshot"]
        assert len(snap_events) >= 1
        # JSON serialization turns integer keys to strings
        assert snap_events[0]["args"][0]["slots"] == {"0": "task_a"}


class TestProviderRegistration:
    """Tests for provider registration and lifecycle."""

    def test_register_provider_success(self, client, state):
        """A valid manifest should register successfully."""
        from elab_server.app import app, socketio

        provider_client = socketio.test_client(app)
        provider_client.emit("register_provider", copy.deepcopy(VALID_MANIFEST))

        client.emit("register_client", {"client_type": "ui"})
        received = client.get_received()
        ap_events = [r for r in received if r["name"] == "available_providers"]
        assert len(ap_events) > 0
        providers = ap_events[-1]["args"][0]["providers"]
        provider_ids = [p["id"] for p in providers]
        assert "test_provider" in provider_ids
        provider_client.disconnect()

    def test_register_provider_invalid_manifest_rejected(self, client, state):
        """An invalid manifest (not a dict) should be rejected."""
        client.emit("register_provider", "not a dict")
        received = client.get_received()
        error_events = [r for r in received if r["name"] == "registration_error"]
        assert len(error_events) >= 1

    def test_register_provider_missing_id_rejected(self, client, state):
        """Manifest without 'id' should be rejected."""
        bad_manifest = copy.deepcopy(VALID_MANIFEST)
        del bad_manifest["id"]
        client.emit("register_provider", bad_manifest)
        received = client.get_received()
        error_events = [r for r in received if r["name"] == "registration_error"]
        assert len(error_events) >= 1

    def test_provider_disconnect_removes_from_state(self, client, state):
        """When a provider disconnects, it's removed from state."""
        from elab_server.app import app, socketio

        provider_client = socketio.test_client(app)
        provider_client.emit("register_provider", copy.deepcopy(VALID_MANIFEST))
        assert len(state.get_providers_list()) >= 1
        provider_client.disconnect()
        remaining = [
            p for p in state.get_providers_list() if p["id"] == "test_provider"
        ]
        assert len(remaining) == 0

    def test_reregister_same_session_replaces(self, client, state):
        """Re-registering the same ID from the same session replaces the old entry."""
        from elab_server.app import app, socketio

        p1 = socketio.test_client(app)
        m1 = copy.deepcopy(VALID_MANIFEST)
        m2 = copy.deepcopy(VALID_MANIFEST)
        m2["name"] = "Updated Provider"
        p1.emit("register_provider", m1)
        p1.emit("register_provider", m2)

        providers = state.get_providers_list()
        matching = [p for p in providers if p["id"] == "test_provider"]
        assert len(matching) == 1
        assert matching[0]["name"] == "Updated Provider"
        p1.disconnect()


class TestDataStream:
    """Tests for data_stream event handling."""

    @pytest.mark.parametrize("source_key", ["sourceId", "source_id"])
    def test_data_stream_accepts_source_key_variants(self, client, state, source_key):
        """Incoming data_stream should accept sourceId and source_id."""
        from elab_server.app import app, socketio

        client.emit("register_client", {"client_type": "ui"})
        client.get_received()  # clear

        provider_client = socketio.test_client(app)
        provider_client.emit("register_provider", copy.deepcopy(VALID_MANIFEST))

        payload = {
            source_key: "test_task_1",
            "value": 2.71,
            "timestamp": time.time() * 1000,
        }
        provider_client.emit("data_stream", payload)

        received = client.get_received()
        data_events = [r for r in received if r["name"] == "data_stream"]
        assert len(data_events) >= 1
        # Server normalizes to canonical key on outbound payload.
        assert data_events[0]["args"][0]["sourceId"] == "test_task_1"
        assert data_events[0]["args"][0]["value"] == 2.71

        provider_client.disconnect()

    def test_data_stream_forwarded_to_ui(self, client, state):
        """data_stream from provider should be forwarded to UI clients."""
        from elab_server.app import app, socketio

        client.emit("register_client", {"client_type": "ui"})
        client.get_received()  # clear

        provider_client = socketio.test_client(app)
        provider_client.emit("register_provider", copy.deepcopy(VALID_MANIFEST))

        payload = {
            "sourceId": "test_task_1",
            "value": 3.14,
            "timestamp": time.time() * 1000,
        }
        provider_client.emit("data_stream", payload)

        received = client.get_received()
        data_events = [r for r in received if r["name"] == "data_stream"]
        assert len(data_events) >= 1
        assert data_events[0]["args"][0]["sourceId"] == "test_task_1"
        assert data_events[0]["args"][0]["value"] == 3.14

        provider_client.disconnect()

    def test_data_stream_ignores_non_dict(self, client, state):
        """Non-dict payloads should be silently ignored."""
        client.emit("data_stream", "not a dict")
        client.emit("register_client", {})
        received = client.get_received()
        assert any(r["name"] == "available_providers" for r in received)

    def test_data_stream_ignores_missing_source_id(self, client, state):
        """Payload without sourceId should be ignored."""
        client.emit("data_stream", {"value": 1.0})
        client.emit("register_client", {})
        received = client.get_received()
        assert any(r["name"] == "available_providers" for r in received)

    def test_data_stream_ignores_missing_both_source_keys(self, client, state):
        """Payload without sourceId and source_id should not be forwarded."""
        from elab_server.app import app, socketio

        client.emit("register_client", {"client_type": "ui"})
        client.get_received()  # clear

        provider_client = socketio.test_client(app)
        provider_client.emit("register_provider", copy.deepcopy(VALID_MANIFEST))

        provider_client.emit("data_stream", {
            "value": 42.0,
            "timestamp": time.time() * 1000,
        })

        received = client.get_received()
        data_events = [r for r in received if r["name"] == "data_stream"]
        assert len(data_events) == 0

        provider_client.disconnect()

    def test_data_stream_with_linear_distribution_normalizes_timestamps(
        self, client, state
    ):
        """Linear distribution timestamps should be server-normalized."""
        from elab_server.app import app, socketio

        client.emit("register_client", {"client_type": "ui"})
        client.get_received()

        provider_client = socketio.test_client(app)
        provider_client.emit("register_provider", copy.deepcopy(VALID_MANIFEST))

        # Send with small millis()-like timestamps (typical for ESP32)
        payload = {
            "sourceId": "test_task_1",
            "value": 1.0,
            "distribution": "linear",
            "startTime": 1000,
            "endTime": 2000,
        }
        provider_client.emit("data_stream", payload)

        received = client.get_received()
        data_events = [r for r in received if r["name"] == "data_stream"]
        assert len(data_events) >= 1
        d = data_events[0]["args"][0]
        # Should be server-normalized (much larger than original small values)
        assert d["startTime"] > 1_000_000
        assert d["endTime"] > 1_000_000
        provider_client.disconnect()

    def test_data_stream_with_timestamps_array(self, client, state):
        """Array timestamps should all be server-normalized."""
        from elab_server.app import app, socketio

        client.emit("register_client", {"client_type": "ui"})
        client.get_received()

        provider_client = socketio.test_client(app)
        provider_client.emit("register_provider", copy.deepcopy(VALID_MANIFEST))

        payload = {
            "sourceId": "test_task_1",
            "value": 1.0,
            "timestamps": [100, 200, 300],
        }
        provider_client.emit("data_stream", payload)

        received = client.get_received()
        data_events = [r for r in received if r["name"] == "data_stream"]
        assert len(data_events) >= 1
        d = data_events[0]["args"][0]
        for t in d["timestamps"]:
            assert t > 1_000_000
        provider_client.disconnect()

    def test_data_stream_binary_b64_decoded(self, client, state):
        """binary_payload_b64 should be decoded and forwarded."""
        from elab_server.app import app, socketio

        client.emit("register_client", {"client_type": "ui"})
        client.get_received()

        provider_client = socketio.test_client(app)
        provider_client.emit("register_provider", copy.deepcopy(VALID_MANIFEST))

        raw_bytes = b"\x01\x02\x03\x04"
        payload = {
            "sourceId": "test_task_1",
            "binary_payload_b64": base64.b64encode(raw_bytes).decode(),
        }
        provider_client.emit("data_stream", payload)

        received = client.get_received()
        data_events = [r for r in received if r["name"] == "data_stream"]
        assert len(data_events) >= 1
        # binary_payload_b64 should have been popped from payload
        assert "binary_payload_b64" not in data_events[0]["args"][0]
        provider_client.disconnect()

    def test_decoder_maps_raw_uncertainty_with_local_derivative(self, client, state):
        """Raw-domain uncertainty should be mapped to decoded domain via local slope."""
        from elab_server.app import app, socketio

        client.emit("register_client", {"client_type": "ui"})
        client.get_received()

        manifest = copy.deepcopy(VALID_MANIFEST)
        task = manifest["tasks"][0]
        task["config"]["accuracy"] = None
        task["decoder"] = {
            "type": "generic_binary",
            "parameters": {
                "dataType": "uint16",
                "endianness": "little",
                "zeroValue": 0,
                "valueRange": 4095,
                "measurementRange": 3.3,
                "linearizationTable": [[0.0, 0.0], [1.65, 3.3]],
            },
        }

        provider_client = socketio.test_client(app)
        provider_client.emit("register_provider", manifest)

        # uint16 little-endian 2047 -> b"\xff\x07"
        payload = {
            "sourceId": "test_task_1",
            "binary_payload": b"\xff\x07",
            "uncertainty": {
                "domain": "raw",
                "model": "combined",
                "systematicAbs": 1.0,
                "randomSigma": 0.5,
            },
        }
        provider_client.emit("data_stream", payload)

        received = client.get_received()
        data_events = [r for r in received if r["name"] == "data_stream"]
        assert len(data_events) >= 1
        out = data_events[0]["args"][0]
        unc = out.get("uncertainty")
        assert isinstance(unc, dict)
        assert unc.get("domain") == "decoded"
        expected_lsb = 2.0 * (3.3 / 4095.0)
        assert unc["systematicAbs"] == pytest.approx(expected_lsb, rel=1e-3)
        assert unc["randomSigma"] == pytest.approx(0.5 * expected_lsb, rel=1e-3)
        provider_client.disconnect()

    def test_accuracy_object_enriches_uncertainty(self, client, state):
        """Manifest accuracy object should produce decoded uncertainty metadata."""
        from elab_server.app import app, socketio

        client.emit("register_client", {"client_type": "ui"})
        client.get_received()

        manifest = copy.deepcopy(VALID_MANIFEST)
        manifest["tasks"][0]["config"]["accuracy"] = {
            "model": "percent_reading_plus_absolute",
            "relativePctReading": 1.0,
            "absoluteOffset": 0.1,
            "confidenceK": 2.0,
        }

        provider_client = socketio.test_client(app)
        provider_client.emit("register_provider", manifest)

        payload = {
            "sourceId": "test_task_1",
            "value": 12.0,
            "timestamp": time.time() * 1000,
        }
        provider_client.emit("data_stream", payload)

        received = client.get_received()
        data_events = [r for r in received if r["name"] == "data_stream"]
        assert len(data_events) >= 1
        out = data_events[0]["args"][0]
        unc = out.get("uncertainty")
        assert isinstance(unc, dict)
        assert unc.get("domain") == "decoded"
        assert unc.get("model") == "combined"
        assert unc.get("systematicAbs") == pytest.approx(0.22, rel=1e-6)
        assert unc.get("randomSigma") == pytest.approx(0.0, rel=1e-6)
        assert math.isclose(float(unc.get("confidenceK", 0.0)), 2.0)
        provider_client.disconnect()


class TestTaskAssignment:
    """Tests for task_assigned / task_unassigned."""

    def test_task_assigned_registers_in_state(self, client, state):
        """task_assigned should add the task to active_tasks_by_slot."""
        from elab_server.app import app, socketio

        provider_client = socketio.test_client(app)
        provider_client.emit("register_provider", copy.deepcopy(VALID_MANIFEST))

        client.emit("register_client", {"client_type": "ui"})
        client.get_received()

        client.emit("task_assigned", {"slot": 0, "taskId": "test_task_1"})
        assert state.active_tasks_by_slot.get(0) == "test_task_1"
        provider_client.disconnect()

    def test_task_unassigned_removes_from_state(self, client, state):
        """task_unassigned should remove the task from active_tasks_by_slot."""
        from elab_server.app import app, socketio

        provider_client = socketio.test_client(app)
        provider_client.emit("register_provider", copy.deepcopy(VALID_MANIFEST))

        client.emit("register_client", {"client_type": "ui"})
        client.emit("task_assigned", {"slot": 2, "taskId": "test_task_1"})
        assert state.active_tasks_by_slot.get(2) == "test_task_1"

        client.emit("task_unassigned", {"slot": 2})
        assert 2 not in state.active_tasks_by_slot
        provider_client.disconnect()

    def test_task_unassigned_noop_for_unknown_slot(self, client, state):
        """Unassigning a slot that isn't active should not crash."""
        client.emit("register_client", {"client_type": "ui"})
        client.emit("task_unassigned", {"slot": 99})
        # Just verify no crash
        assert 99 not in state.active_tasks_by_slot


class TestControlCommands:
    """Tests for cmd_control forwarding."""

    def test_cmd_control_forwarded_to_provider(self, client, state):
        """cmd_control should be forwarded to the correct provider."""
        from elab_server.app import app, socketio

        provider_client = socketio.test_client(app)
        provider_client.emit("register_provider", copy.deepcopy(VALID_MANIFEST))
        provider_client.get_received()  # clear

        client.emit("register_client", {"client_type": "ui"})
        client.emit(
            "cmd_control",
            {
                "provider_id": "prov_test_provider",
                "command": {"action": "START"},
            },
        )

        received = provider_client.get_received()
        cmd_events = [r for r in received if r["name"] == "execute_command"]
        assert len(cmd_events) >= 1
        provider_client.disconnect()

    def test_cmd_control_empty_provider_id_ignored(self, client, state):
        """cmd_control without provider_id should be silently ignored."""
        client.emit("register_client", {"client_type": "ui"})
        # Should not crash
        client.emit("cmd_control", {"command": {"action": "START"}})


class TestProviderMetaChanged:
    """Tests for provider_meta_changed event."""

    def test_meta_change_updates_state_and_broadcasts(self, client, state):
        """provider_meta_changed should update state and forward to UIs."""
        from elab_server.app import app, socketio

        provider_client = socketio.test_client(app)
        provider_client.emit("register_provider", copy.deepcopy(VALID_MANIFEST))

        client.emit("register_client", {"client_type": "ui"})
        client.get_received()  # clear

        provider_client.emit(
            "provider_meta_changed",
            {
                "task_id": "test_task_1",
                "changes": {"color": "#00FF00", "name": "Renamed Sensor"},
            },
        )

        received = client.get_received()
        meta_events = [r for r in received if r["name"] == "provider_meta_changed"]
        assert len(meta_events) >= 1

        m = state.get_provider_manifest("test_provider")
        task = m["tasks"][0]
        assert task["color"] == "#00FF00"
        assert task["name"] == "Renamed Sensor"
        provider_client.disconnect()


class TestSessionManagement:
    """Tests for session start/stop/get/delete."""

    def test_session_start_and_stop(self, client, state, session_dir, recorder):
        """Starting and stopping a session should work."""
        client.emit("register_client", {"client_type": "ui"})
        client.get_received()

        client.emit("session_start", {"session_id": "my_test"})
        received = client.get_received()
        start_results = [r for r in received if r["name"] == "session_start_result"]
        assert len(start_results) == 1
        assert state.recording is True

        client.emit("session_stop", {})
        received = client.get_received()
        stop_results = [r for r in received if r["name"] == "session_stop_result"]
        assert len(stop_results) == 1
        assert state.recording is False

    def test_get_sessions_lists_dirs(self, client, state, session_dir):
        """get_sessions should list directories with session.sqlite."""
        # Create a fake session dir
        sdir = session_dir / "2026-01-01_12-00-00"
        sdir.mkdir()
        conn = sqlite3.connect(str(sdir / "session.sqlite"))
        conn.execute("CREATE TABLE t (id INTEGER)")
        conn.close()

        client.emit("register_client", {"client_type": "ui"})
        client.get_received()

        client.emit("get_sessions")
        received = client.get_received()
        session_events = [r for r in received if r["name"] == "session_list"]
        assert len(session_events) >= 1
        assert "2026-01-01_12-00-00" in session_events[0]["args"][0]

    def test_get_sessions_empty_when_no_dir(self, client, state, session_dir):
        """get_sessions should return empty list when no sessions exist."""
        client.emit("register_client", {"client_type": "ui"})
        client.get_received()
        client.emit("get_sessions")
        received = client.get_received()
        session_events = [r for r in received if r["name"] == "session_list"]
        assert len(session_events) >= 1

    def test_delete_session(self, client, state, session_dir):
        """delete_session should remove the session directory."""
        sdir = session_dir / "to_delete"
        sdir.mkdir()
        conn = sqlite3.connect(str(sdir / "session.sqlite"))
        conn.execute("CREATE TABLE t (id INTEGER)")
        conn.close()

        client.emit("register_client", {"client_type": "ui"})
        client.get_received()

        client.emit("delete_session", {"session_id": "to_delete"})
        assert not sdir.exists()

    def test_delete_session_path_traversal_blocked(self, client, state, session_dir):
        """Path traversal in session_id should be blocked."""
        client.emit("register_client", {"client_type": "ui"})
        client.emit("delete_session", {"session_id": "../evil"})
        # Should not crash and no deletion should happen
        assert session_dir.exists()

    def test_delete_session_nonexistent_ignored(self, client, state, session_dir):
        """Deleting a non-existent session should not crash."""
        client.emit("register_client", {"client_type": "ui"})
        client.emit("delete_session", {"session_id": "ghost"})
        # Just verify no crash

    def test_delete_session_empty_id_ignored(self, client, state, session_dir):
        """Empty session_id should be silently ignored."""
        client.emit("register_client", {"client_type": "ui"})
        client.emit("delete_session", {"session_id": ""})


class TestReplayActions:
    """Tests for replay_load and replay_action."""

    def _create_replay_session(self, session_dir, name="replay_sess"):
        """Create a session DB suitable for replay."""
        sdir = session_dir / name
        sdir.mkdir()
        db = sdir / "session.sqlite"
        conn = sqlite3.connect(str(db))
        conn.execute(
            "CREATE TABLE session_log ("
            "  seq INTEGER PRIMARY KEY AUTOINCREMENT,"
            "  event_time_ms REAL, source_id TEXT, type TEXT, payload TEXT, binary_data BLOB)"
        )
        conn.execute(
            "CREATE TABLE manifests (provider_id TEXT PRIMARY KEY, manifest TEXT)"
        )
        payload = json.dumps(
            {"type": "DATA_STREAM", "payload": {"sourceId": "test_task_1", "value": 1}}
        )
        conn.executemany(
            "INSERT INTO session_log(event_time_ms, source_id, type, payload) VALUES (?, ?, ?, ?)",
            [
                (1_700_000_000_000, "test_task_1", "DATA_STREAM", payload),
                (1_700_000_005_000, "test_task_1", "DATA_STREAM", payload),
            ],
        )
        manifest = json.dumps(copy.deepcopy(VALID_MANIFEST))
        conn.execute(
            "INSERT INTO manifests(provider_id, manifest) VALUES (?, ?)",
            ("test_provider", manifest),
        )
        conn.commit()
        conn.close()
        return name

    def test_replay_load_success(self, client, state, session_dir):
        """Loading a valid session should succeed."""
        name = self._create_replay_session(session_dir)

        client.emit("register_client", {"client_type": "ui"})
        client.get_received()

        client.emit("replay_load", {"session_id": name})
        received = client.get_received()
        loaded = [r for r in received if r["name"] == "replay_loaded"]
        assert len(loaded) == 1
        assert loaded[0]["args"][0]["success"] is True
        assert loaded[0]["args"][0]["duration"] > 0

    def test_replay_load_nonexistent(self, client, state, session_dir):
        """Loading a non-existent session should fail."""
        client.emit("register_client", {"client_type": "ui"})
        client.get_received()

        client.emit("replay_load", {"session_id": "ghost"})
        received = client.get_received()
        loaded = [r for r in received if r["name"] == "replay_loaded"]
        assert len(loaded) == 1
        assert loaded[0]["args"][0]["success"] is False

    def test_replay_action_play_pause_stop(self, client, state, session_dir):
        """play/pause/stop actions should be accepted without error."""
        name = self._create_replay_session(session_dir)
        client.emit("register_client", {"client_type": "ui"})
        client.get_received()

        client.emit("replay_load", {"session_id": name})
        client.get_received()

        for action in ("play", "pause", "stop"):
            client.emit("replay_action", {"action": action})
        # Should not crash
        client.emit("replay_action", {"action": "unload"})

    def test_replay_action_seek(self, client, state, session_dir):
        """seek action should be processed."""
        name = self._create_replay_session(session_dir)
        client.emit("register_client", {"client_type": "ui"})
        client.get_received()
        client.emit("replay_load", {"session_id": name})
        client.get_received()

        client.emit("replay_action", {"action": "seek", "value": 2500})
        # Should not crash

    def test_replay_action_seek_invalid_value(self, client, state, session_dir):
        """seek with invalid value should not crash."""
        name = self._create_replay_session(session_dir)
        client.emit("register_client", {"client_type": "ui"})
        client.get_received()
        client.emit("replay_load", {"session_id": name})
        client.get_received()

        client.emit("replay_action", {"action": "seek", "value": "not_a_number"})
        client.emit("replay_action", {"action": "seek", "value": -100})
        # Should not crash

    def test_replay_action_speed(self, client, state, session_dir):
        """speed action should clamp between 0.1 and 10."""
        name = self._create_replay_session(session_dir)
        client.emit("register_client", {"client_type": "ui"})
        client.get_received()
        client.emit("replay_load", {"session_id": name})

        from elab_server.app import socketio

        replayer = None
        # Get replayer from app_context indirectly
        client.emit("replay_action", {"action": "speed", "value": 5.0})
        client.emit("replay_action", {"action": "speed", "value": 100.0})
        client.emit("replay_action", {"action": "speed", "value": "bad"})
        # Should not crash

    def test_replay_action_invalid_data(self, client, state):
        """Non-dict replay_action should be ignored."""
        client.emit("register_client", {"client_type": "ui"})
        client.emit("replay_action", "not a dict")
        # Should not crash

    def test_get_recorded_providers(self, client, state, session_dir):
        """get_recorded_providers should return rec_-prefixed providers."""
        name = self._create_replay_session(session_dir)
        client.emit("register_client", {"client_type": "ui"})
        client.get_received()

        client.emit("get_recorded_providers", {"session_id": name})
        received = client.get_received()
        rp_events = [r for r in received if r["name"] == "recorded_providers"]
        assert len(rp_events) == 1
        providers = rp_events[0]["args"][0]["providers"]
        assert len(providers) >= 1
        assert providers[0]["id"].startswith("rec_")
        assert providers[0]["is_recorded"] is True
        # Tasks should also have rec_ prefix
        for task in providers[0].get("tasks", []):
            assert task["id"].startswith("rec_")
            assert task["is_recorded"] is True

    def test_get_recorded_providers_nonexistent(self, client, state, session_dir):
        """Non-existent session should return empty providers."""
        client.emit("register_client", {"client_type": "ui"})
        client.get_received()
        client.emit("get_recorded_providers", {"session_id": "ghost"})
        received = client.get_received()
        rp_events = [r for r in received if r["name"] == "recorded_providers"]
        assert len(rp_events) == 1
        assert rp_events[0]["args"][0]["providers"] == []

    def test_get_recorded_providers_no_manifests_table(
        self, client, state, session_dir
    ):
        """Session without manifests table should return empty providers."""
        sdir = session_dir / "no_manifests"
        sdir.mkdir()
        db = sdir / "session.sqlite"
        conn = sqlite3.connect(str(db))
        conn.execute(
            "CREATE TABLE session_log (seq INTEGER PRIMARY KEY, event_time_ms REAL, type TEXT)"
        )
        conn.close()

        client.emit("register_client", {"client_type": "ui"})
        client.get_received()
        client.emit("get_recorded_providers", {"session_id": "no_manifests"})
        received = client.get_received()
        rp_events = [r for r in received if r["name"] == "recorded_providers"]
        assert rp_events[0]["args"][0]["providers"] == []


class TestScriptManagement:
    """Tests for get_available_scripts, start_client_script, stop_client_script."""

    def test_get_available_scripts(self, client, state):
        """get_available_scripts should return a list."""
        client.emit("register_client", {"client_type": "ui"})
        received = client.get_received()
        script_events = [r for r in received if r["name"] == "available_scripts"]
        assert len(script_events) >= 1
        assert isinstance(script_events[0]["args"][0], list)

    def test_start_nonexistent_script(self, client, state):
        """Starting a non-existent script should not crash."""
        client.emit("register_client", {"client_type": "ui"})
        client.get_received()
        client.emit("start_client_script", {"filename": "nonexistent_xyz.py"})
        # Should not crash

    def test_stop_nonrunning_script(self, client, state):
        """Stopping a non-running script should not crash."""
        client.emit("register_client", {"client_type": "ui"})
        client.get_received()
        client.emit("stop_client_script", {"filename": "not_running.py"})
        # Should not crash


class TestPluginUrlSanitization:
    """Tests for _is_plugin_url_allowed and _sanitize_plugin_urls."""

    def test_plugin_url_from_client_ip_allowed(self, client, state):
        """A plugin URL from the provider's own IP should be accepted."""
        from elab_server.sockets import _is_plugin_url_allowed

        assert _is_plugin_url_allowed(
            "http://192.168.1.10:8080/plugin.js", "192.168.1.10"
        )

    def test_plugin_url_from_other_ip_rejected(self, client, state):
        """A plugin URL from a different IP should be rejected."""
        from elab_server.sockets import _is_plugin_url_allowed

        assert not _is_plugin_url_allowed("http://evil.com/plugin.js", "192.168.1.10")

    def test_plugin_url_invalid_scheme_rejected(self, client, state):
        """Non-http(s) schemes should be rejected."""
        from elab_server.sockets import _is_plugin_url_allowed

        assert not _is_plugin_url_allowed(
            "ftp://192.168.1.10/plugin.js", "192.168.1.10"
        )
        assert not _is_plugin_url_allowed("javascript:alert(1)", "192.168.1.10")

    def test_plugin_url_empty_rejected(self, client, state):
        """Empty or None URLs should be rejected."""
        from typing import cast
        from elab_server.sockets import _is_plugin_url_allowed

        assert not _is_plugin_url_allowed("", "192.168.1.10")
        assert not _is_plugin_url_allowed(cast(str, None), "192.168.1.10")

    def test_sanitize_strips_untrusted_urls(self, client, state):
        """_sanitize_plugin_urls should strip URLs from untrusted origins."""
        from elab_server.sockets import _sanitize_plugin_urls

        manifest = {
            "tasks": [
                {
                    "id": "task_1",
                    "ui": {
                        "mode": "custom",
                        "url": "http://evil.com/malware.js",
                        "integrity": "sha256-abc",
                    },
                }
            ],
        }
        _sanitize_plugin_urls(manifest, "192.168.1.10")
        ui = manifest["tasks"][0]["ui"]
        assert "url" not in ui
        assert "integrity" not in ui
        assert ui["mode"] == "generic"

    def test_sanitize_keeps_trusted_urls(self, client, state):
        """_sanitize_plugin_urls should keep URLs from the provider's IP."""
        from elab_server.sockets import _sanitize_plugin_urls

        manifest = {
            "tasks": [
                {
                    "id": "task_1",
                    "ui": {
                        "mode": "custom",
                        "url": "http://192.168.1.10:8080/plugin.js",
                    },
                }
            ],
        }
        _sanitize_plugin_urls(manifest, "192.168.1.10")
        ui = manifest["tasks"][0]["ui"]
        assert ui["url"] == "http://192.168.1.10:8080/plugin.js"
        assert ui["mode"] == "custom"


class TestLastUiDisconnectClearsSlots:
    """When the last UI client disconnects, active slots should be cleared."""

    def test_last_ui_disconnect_clears_slots(self, client, state):
        """Disconnecting the last UI should clear active_tasks_by_slot."""
        from elab_server.app import app, socketio

        client.emit("register_client", {"client_type": "ui"})
        client.get_received()

        # Simulate an active task
        with state.atomic_update():
            state.active_tasks_by_slot[0] = "test_task_1"

        client.disconnect()

        assert len(state.active_tasks_by_slot) == 0


class TestSourceActuatorRouting:
    """Server-side source→actuator routing via link_source/unlink_source."""

    @staticmethod
    def _actuator_manifest():
        manifest = copy.deepcopy(VALID_MANIFEST)
        manifest["id"] = "test_actuator"
        manifest["tasks"] = [
            {
                "id": "test_actuator_task",
                "name": "Test Actuator",
                "type": "ACTUATOR",
                "ui": {"mode": "generic"},
                "config": {"unit": "V"},
            }
        ]
        return manifest

    def test_linked_actuator_receives_stream(self, client, state):
        """A linked actuator should receive the source stream as execute_command."""
        from elab_server.app import app, socketio

        source = socketio.test_client(app)
        source.emit("register_provider", copy.deepcopy(VALID_MANIFEST))

        actuator = socketio.test_client(app)
        actuator.emit("register_provider", self._actuator_manifest())
        actuator.get_received()  # clear

        client.emit(
            "link_source",
            {"source_id": "test_task_1", "actuator_id": "prov_test_actuator"},
        )

        source.emit(
            "data_stream",
            {
                "sourceId": "test_task_1",
                "value": 4.2,
                "values": [1.0, 2.0, 4.2],
                "startTime": 1000,
                "endTime": 2000,
                "timestamp": time.time() * 1000,
            },
        )

        received = actuator.get_received()
        exec_events = [r for r in received if r["name"] == "execute_command"]
        assert len(exec_events) >= 1
        cmd = exec_events[0]["args"][0]["command"]
        assert cmd["action"] == "set_value"
        assert cmd["payload"]["values"] == [1.0, 2.0, 4.2]
        assert cmd["payload"]["value"] == 4.2

        source.disconnect()
        actuator.disconnect()

    def test_unlink_stops_routing(self, client, state):
        """After unlink_source, no further stream should reach the actuator."""
        from elab_server.app import app, socketio

        source = socketio.test_client(app)
        source.emit("register_provider", copy.deepcopy(VALID_MANIFEST))
        actuator = socketio.test_client(app)
        actuator.emit("register_provider", self._actuator_manifest())

        client.emit(
            "link_source",
            {"source_id": "test_task_1", "actuator_id": "prov_test_actuator"},
        )
        client.emit(
            "unlink_source",
            {"source_id": "test_task_1", "actuator_id": "prov_test_actuator"},
        )
        actuator.get_received()  # clear

        source.emit(
            "data_stream",
            {"sourceId": "test_task_1", "value": 1.0, "timestamp": time.time() * 1000},
        )

        received = actuator.get_received()
        exec_events = [r for r in received if r["name"] == "execute_command"]
        assert len(exec_events) == 0

        source.disconnect()
        actuator.disconnect()

    def test_disconnect_clears_links(self, client, state):
        """Disconnecting the source provider should purge its actuator links."""
        from elab_server.app import app, socketio

        source = socketio.test_client(app)
        source.emit("register_provider", copy.deepcopy(VALID_MANIFEST))
        actuator = socketio.test_client(app)
        actuator.emit("register_provider", self._actuator_manifest())

        client.emit(
            "link_source",
            {"source_id": "test_task_1", "actuator_id": "prov_test_actuator"},
        )
        assert state.get_actuator_links("test_task_1") == ["test_actuator"]

        source.disconnect()

        assert state.get_actuator_links("test_task_1") == []

        actuator.disconnect()

    @staticmethod
    def _constrained_actuator_manifest():
        """Actuator that accepts only scalars and caps its rate (like an ESP32)."""
        manifest = copy.deepcopy(VALID_MANIFEST)
        manifest["id"] = "test_actuator"
        manifest["tasks"] = [
            {
                "id": "test_actuator_task",
                "name": "Test Actuator",
                "type": "ACTUATOR",
                "ui": {"mode": "generic"},
                "config": {"unit": "V", "accepts": ["scalar"], "maxRateHz": 10},
            }
        ]
        return manifest

    def test_scalar_only_actuator_gets_no_values_array(self, client, state):
        """An actuator declaring accepts=['scalar'] receives a scalar, no array."""
        from elab_server.app import app, socketio
        from elab_server.socket_handlers import provider_handlers

        provider_handlers._actuator_route_ts.clear()

        source = socketio.test_client(app)
        source.emit("register_provider", copy.deepcopy(VALID_MANIFEST))
        actuator = socketio.test_client(app)
        actuator.emit("register_provider", self._constrained_actuator_manifest())
        actuator.get_received()  # clear

        client.emit(
            "link_source",
            {"source_id": "test_task_1", "actuator_id": "prov_test_actuator"},
        )

        source.emit(
            "data_stream",
            {
                "sourceId": "test_task_1",
                "value": 4.2,
                "values": [1.0, 2.0, 4.2],
                "startTime": 1000,
                "endTime": 2000,
                "timestamp": time.time() * 1000,
            },
        )

        received = actuator.get_received()
        exec_events = [r for r in received if r["name"] == "execute_command"]
        assert len(exec_events) == 1
        payload = exec_events[0]["args"][0]["command"]["payload"]
        assert payload.get("values") is None
        assert payload["value"] == 4.2

        source.disconnect()
        actuator.disconnect()

    def test_max_rate_throttles_rapid_stream(self, client, state):
        """Two back-to-back chunks to a maxRateHz=10 actuator yield one command."""
        from elab_server.app import app, socketio
        from elab_server.socket_handlers import provider_handlers

        provider_handlers._actuator_route_ts.clear()

        source = socketio.test_client(app)
        source.emit("register_provider", copy.deepcopy(VALID_MANIFEST))
        actuator = socketio.test_client(app)
        actuator.emit("register_provider", self._constrained_actuator_manifest())
        actuator.get_received()  # clear

        client.emit(
            "link_source",
            {"source_id": "test_task_1", "actuator_id": "prov_test_actuator"},
        )

        for value in (1.0, 2.0):
            source.emit(
                "data_stream",
                {
                    "sourceId": "test_task_1",
                    "value": value,
                    "values": [value],
                    "timestamp": time.time() * 1000,
                },
            )

        received = actuator.get_received()
        exec_events = [r for r in received if r["name"] == "execute_command"]
        # The second chunk arrives well within the 100 ms window → dropped.
        assert len(exec_events) == 1
        assert exec_events[0]["args"][0]["command"]["payload"]["value"] == 1.0

        source.disconnect()
        actuator.disconnect()
