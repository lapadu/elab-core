"""Tests for elab_bridge.BridgeDaemon (unit-level, mocked dispatcher)."""
import os
import sqlite3
import threading
import time
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from elab_bridge.bridge_daemon import BridgeDaemon, ConnectedNode


class TestConnectedNode:
    """Tests for the ConnectedNode helper class."""

    def test_initial_state(self):
        """New node starts alive."""
        node = ConnectedNode(
            node_id="test_node",
            manifest={"id": "test_node", "name": "Test", "tasks": []},
        )
        assert node.is_alive
        assert node.node_id == "test_node"

    def test_touch_updates_timestamp(self):
        """touch() refreshes liveness."""
        node = ConnectedNode(
            node_id="n1",
            manifest={"id": "n1", "name": "N1", "tasks": []},
        )
        old_ts = node.last_seen
        time.sleep(0.01)
        node.touch()
        assert node.last_seen > old_ts


class TestBridgeDaemonControlMessages:
    """Tests for control message handling logic."""

    def _make_daemon(self) -> BridgeDaemon:
        """Create a daemon without starting network connections."""
        daemon = BridgeDaemon.__new__(BridgeDaemon)
        daemon._nodes = {}
        daemon._nodes_lock = threading.Lock()
        daemon._running = False
        daemon._sio = MagicMock()
        daemon._sio.connected = True
        daemon._notify_socket = MagicMock()
        daemon._zmq_ctx = None
        daemon._control_socket = None
        return daemon

    def test_handle_register_valid(self):
        """Valid registration stores the node and emits to dispatcher."""
        daemon = self._make_daemon()
        msg = {
            "type": "register",
            "manifest": {
                "id": "script_01",
                "name": "My Script",
                "category": "VIRTUAL_SCRIPT",
                "providerVersion": "1.0.0",
                "apiVersion": "2.0.0",
                "persistConfig": False,
                "tasks": [
                    {
                        "id": "task_a",
                        "name": "Task A",
                        "type": "SENSOR",
                        "ui": {"mode": "generic", "template": "tpl_generic_sensor"},
                    }
                ],
            },
        }
        resp = daemon._handle_register(msg)
        assert resp["status"] == "ok"
        assert "script_01" in daemon._nodes
        daemon._sio.emit.assert_called_once()

    def test_handle_register_replaces_existing_node(self):
        """Re-registering same node id replaces old node and frees old SHM."""
        daemon = self._make_daemon()
        old_node = ConnectedNode(
            node_id="script_01",
            manifest={"id": "script_01", "name": "Old", "tasks": []},
        )
        old_ch = MagicMock()
        old_node.shm_channels["old_task"] = old_ch
        daemon._nodes["script_01"] = old_node

        msg = {
            "type": "register",
            "manifest": {
                "id": "script_01",
                "name": "New Script",
                "category": "VIRTUAL_SCRIPT",
                "providerVersion": "1.0.0",
                "apiVersion": "2.0.0",
                "persistConfig": False,
                "tasks": [],
            },
        }

        resp = daemon._handle_register(msg)

        assert resp["status"] == "ok"
        old_ch.close.assert_called_once()
        old_ch.unlink.assert_called_once()
        assert daemon._nodes["script_01"].manifest["name"] == "New Script"

    def test_handle_register_missing_manifest(self):
        """Registration without manifest fails."""
        daemon = self._make_daemon()
        resp = daemon._handle_register({"type": "register"})
        assert resp["status"] == "error"

    def test_handle_deregister(self):
        """Deregistering removes the node."""
        daemon = self._make_daemon()
        node = ConnectedNode("n1", {"id": "n1", "name": "N", "tasks": []})
        daemon._nodes["n1"] = node
        resp = daemon._handle_deregister({"type": "deregister", "node_id": "n1"})
        assert resp["status"] == "ok"
        assert "n1" not in daemon._nodes

    def test_handle_deregister_unknown(self):
        """Deregistering an unknown node returns error."""
        daemon = self._make_daemon()
        resp = daemon._handle_deregister({"type": "deregister", "node_id": "ghost"})
        assert resp["status"] == "error"

    def test_handle_actor_command(self):
        """Actor commands are forwarded to the dispatcher."""
        daemon = self._make_daemon()
        resp = daemon._handle_actor_command({
            "type": "actor_command",
            "target_task_id": "relay_01",
            "action": "toggle",
            "payload": {"state": True},
        })
        assert resp["status"] == "ok"
        daemon._sio.emit.assert_called_once_with("update_config", {
            "target_task_id": "relay_01",
            "action": "toggle",
            "payload": {"state": True},
        })

    def test_handle_unknown_type(self):
        """Unknown message types return an error."""
        daemon = self._make_daemon()
        resp = daemon._handle_control_message({"type": "bogus"})
        assert resp["status"] == "error"

    def test_find_node_for_task(self):
        """_find_node_for_task locates the owner node."""
        daemon = self._make_daemon()
        daemon._nodes["n1"] = ConnectedNode(
            "n1",
            {"id": "n1", "name": "N1", "tasks": [{"id": "task_x"}]},
        )
        assert daemon._find_node_for_task("task_x") == "n1"
        assert daemon._find_node_for_task("nonexistent") is None

    def test_handle_data_available_missing_task(self):
        daemon = self._make_daemon()
        resp = daemon._handle_data_available({"type": "data_available", "count": 1})
        assert resp["status"] == "error"

    def test_handle_data_available_missing_channel(self):
        daemon = self._make_daemon()
        node = ConnectedNode("n1", {"id": "n1", "tasks": [{"id": "task_x"}]})
        daemon._nodes["n1"] = node
        resp = daemon._handle_data_available({"type": "data_available", "task_id": "task_x", "count": 1})
        assert resp["status"] == "error"

    def test_handle_data_available_success_streams_to_dispatcher(self):
        daemon = self._make_daemon()
        node = ConnectedNode("n1", {"id": "n1", "tasks": [{"id": "task_x"}]})
        ch = MagicMock()
        ch.read_latest.return_value = np.array([1.0, 2.0], dtype=np.float32)
        node.shm_channels["task_x"] = ch
        daemon._nodes["n1"] = node

        resp = daemon._handle_data_available({
            "type": "data_available",
            "task_id": "task_x",
            "count": 2,
            "timestamp_ns": 1000,
        })
        assert resp["status"] == "ok"
        daemon._sio.emit.assert_called_with("data_stream", {
            "sourceId": "task_x",
            "values": [1.0, 2.0],
            "timestamp": 1e-06,
        })

    def test_handle_actor_command_missing_fields(self):
        daemon = self._make_daemon()
        resp = daemon._handle_actor_command({"type": "actor_command", "action": "toggle"})
        assert resp["status"] == "error"

    def test_handle_heartbeat_ack_touches_node(self):
        daemon = self._make_daemon()
        node = ConnectedNode("n1", {"id": "n1", "tasks": []})
        daemon._nodes["n1"] = node
        old = node.last_seen
        time.sleep(0.01)
        resp = daemon._handle_heartbeat_ack({"type": "heartbeat_ack", "node_id": "n1"})
        assert resp["status"] == "ok"
        assert node.last_seen > old

    def test_handle_fetch_history_missing_fields(self):
        daemon = self._make_daemon()
        resp = daemon._handle_fetch_history({"type": "fetch_history", "session_id": "s1"})
        assert resp["status"] == "error"

    def test_handle_fetch_history_session_not_found(self, tmp_path, monkeypatch):
        daemon = self._make_daemon()
        monkeypatch.setattr("elab_server.config.SESSION_DIR", str(tmp_path))
        resp = daemon._handle_fetch_history({"type": "fetch_history", "session_id": "nope", "source_id": "src"})
        assert resp["status"] == "error"

    def test_handle_fetch_history_success(self, tmp_path, monkeypatch):
        daemon = self._make_daemon()
        monkeypatch.setattr("elab_server.config.SESSION_DIR", str(tmp_path))

        session_dir = tmp_path / "s1"
        session_dir.mkdir()
        db = session_dir / "session.sqlite"
        conn = sqlite3.connect(db)
        cur = conn.cursor()
        cur.execute("CREATE TABLE stream_data (source_id TEXT, value REAL, timestamp REAL)")
        cur.execute("INSERT INTO stream_data VALUES (?, ?, ?)", ("src", 1.2, 10.0))
        cur.execute("INSERT INTO stream_data VALUES (?, ?, ?)", ("src", 2.3, 11.0))
        conn.commit()
        conn.close()

        resp = daemon._handle_fetch_history({"type": "fetch_history", "session_id": "s1", "source_id": "src"})
        assert resp["status"] == "ok"
        assert resp["data"] == [1.2, 2.3]


class TestBridgeDaemonForwarding:
    """Forwarding behavior tests."""

    def _make_daemon(self) -> BridgeDaemon:
        daemon = BridgeDaemon.__new__(BridgeDaemon)
        daemon._nodes = {}
        daemon._nodes_lock = threading.Lock()
        daemon._running = False
        daemon._sio = MagicMock()
        daemon._sio.connected = True
        daemon._notify_socket = MagicMock()
        daemon._zmq_ctx = None
        daemon._control_socket = None
        return daemon

    def test_forward_config_update_sends_to_owner(self):
        daemon = self._make_daemon()
        daemon._nodes["n1"] = ConnectedNode("n1", {"id": "n1", "tasks": [{"id": "task_x"}]})

        daemon._forward_config_update({"task_id": "task_x", "key": "k", "value": 1})

        daemon._notify_socket.send_multipart.assert_called_once()

    def test_forward_execute_command_update_input(self):
        daemon = self._make_daemon()
        daemon._nodes["n1"] = ConnectedNode("n1", {"id": "n1", "tasks": [{"id": "task_x"}]})

        daemon._forward_execute_command({
            "provider_id": "prov_task_x",
            "command": {"action": "update_input", "payload": {"source": {"id": "src"}}},
        })

        daemon._notify_socket.send_multipart.assert_called_once()

    def test_forward_execute_command_ignores_unknown_action(self):
        daemon = self._make_daemon()
        daemon._nodes["n1"] = ConnectedNode("n1", {"id": "n1", "tasks": [{"id": "task_x"}]})

        daemon._forward_execute_command({
            "provider_id": "prov_task_x",
            "command": {"action": "noop", "payload": {}},
        })

        daemon._notify_socket.send_multipart.assert_not_called()

    def test_forward_stream_data_with_values(self):
        daemon = self._make_daemon()
        daemon._forward_stream_data({"source_id": "src", "values": [1, 2]})
        daemon._notify_socket.send_multipart.assert_called_once()

    def test_forward_stream_data_with_single_value(self):
        daemon = self._make_daemon()
        daemon._forward_stream_data({"sourceId": "src", "value": 3.5})
        daemon._notify_socket.send_multipart.assert_called_once()

    def test_forward_stream_data_no_values_is_noop(self):
        daemon = self._make_daemon()
        daemon._forward_stream_data({"source_id": "src"})
        daemon._notify_socket.send_multipart.assert_not_called()

    def test_deregister_node_closes_shm_and_emits(self):
        daemon = self._make_daemon()
        node = ConnectedNode("n1", {"id": "n1", "tasks": []})
        ch = MagicMock()
        node.shm_channels["t1"] = ch

        daemon._deregister_node(node)

        ch.close.assert_called_once()
        ch.unlink.assert_called_once()
        daemon._sio.emit.assert_called_once_with("deregister_provider", {"provider_id": "n1"})
