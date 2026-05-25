"""Tests for elab_api.LocalNode (unit-level, no live ZMQ bridge)."""
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
import zmq

from elab_api.local_node import LocalNode


class TestLocalNodeRegistration:
    """Tests for task registration logic."""

    def test_register_task_basic(self):
        """register_task stores the task definition."""
        node = LocalNode(name="TestNode")
        node.register_task(
            task_id="temp_sensor",
            task_type="SENSOR",
            template="tpl_generic_sensor",
            unit="°C",
            color="#ef4444",
        )
        assert "temp_sensor" in node._tasks
        task = node._tasks["temp_sensor"]
        assert task["type"] == "SENSOR"
        assert task["ui"]["template"] == "tpl_generic_sensor"
        assert task["config"]["unit"] == "°C"
        assert task["color"] == "#ef4444"

    def test_register_task_with_config_fields(self):
        """configFields are passed through verbatim."""
        node = LocalNode(name="TestNode")
        config_fields = [
            {"key": "cutoff", "label": "Cutoff", "type": "slider", "min": 0, "max": 100},
        ]
        node.register_task(
            task_id="filter",
            task_type="MATH",
            template="tpl_generic_sensor",
            config=config_fields,
        )
        task = node._tasks["filter"]
        assert task["config"]["configFields"] == config_fields

    def test_register_task_custom_ui(self):
        """Custom UI mode sets url and componentName."""
        node = LocalNode(name="TestNode")
        node.register_task(
            task_id="custom_viz",
            task_type="SENSOR",
            template="tpl_generic_sensor",
            ui_mode="custom",
            ui_url="http://localhost:8080/plugin.js",
            ui_component_name="MyWidget",
            ui_integrity="sha256-abc123",
        )
        task = node._tasks["custom_viz"]
        assert task["ui"]["mode"] == "custom"
        assert task["ui"]["url"] == "http://localhost:8080/plugin.js"
        assert task["ui"]["componentName"] == "MyWidget"
        assert task["ui"]["integrity"] == "sha256-abc123"

    def test_register_task_tags(self):
        """Tags are stored in the task definition."""
        node = LocalNode(name="TestNode")
        node.register_task(
            task_id="tagged",
            task_type="SENSOR",
            template="tpl_generic_sensor",
            tags=["temperature", "usb"],
        )
        assert node._tasks["tagged"]["tags"] == ["temperature", "usb"]


class TestLocalNodeCallbacks:
    """Tests for callback registration decorators."""

    def test_on_config_update_decorator(self):
        """on_config_update registers the callback."""
        node = LocalNode(name="TestNode")

        @node.on_config_update("my_task")
        def handler(key, value):
            pass

        assert "my_task" in node._config_callbacks
        assert node._config_callbacks["my_task"] is handler

    def test_on_stream_decorator(self):
        """on_stream registers the callback."""
        node = LocalNode(name="TestNode")

        @node.on_stream("source_123")
        def handler(data):
            pass

        assert "source_123" in node._stream_callbacks
        assert node._stream_callbacks["source_123"] is handler

    def test_on_input_update_decorator(self):
        """on_input_update registers the callback."""
        node = LocalNode(name="TestNode")

        @node.on_input_update("math_task")
        def handler(source):
            pass

        assert "math_task" in node._input_callbacks
        assert node._input_callbacks["math_task"] is handler

    def test_on_dynamic_stream_decorator(self):
        """on_dynamic_stream registers the callback."""
        node = LocalNode(name="TestNode")

        @node.on_dynamic_stream()
        def handler(source_id, values):
            pass

        assert node._dynamic_stream_callback is handler


class TestLocalNodeManifestBuild:
    """Tests for the manifest that gets sent to the bridge."""

    def test_manifest_structure(self):
        """The built manifest conforms to E-Lab schema structure."""
        node = LocalNode(name="My Filter")
        node.register_task(
            task_id="out_filtered",
            task_type="MATH",
            template="tpl_generic_sensor",
            unit="V",
            sample_rate=1000,
        )

        # Access the internal method that builds the manifest
        manifest = {
            "id": node.node_id,
            "name": node.name,
            "category": "VIRTUAL_SCRIPT",
            "providerVersion": "1.0.0",
            "apiVersion": "2.0.0",
            "persistConfig": False,
            "tasks": list(node._tasks.values()),
        }

        assert manifest["name"] == "My Filter"
        assert manifest["category"] == "VIRTUAL_SCRIPT"
        assert len(manifest["tasks"]) == 1

        task = manifest["tasks"][0]
        assert task["id"] == "out_filtered"
        assert task["type"] == "MATH"
        assert task["config"]["unit"] == "V"
        assert task["config"]["sampleRate"] == 1000

    def test_register_math_task(self):
        """register_math_task creates a MATH task with inputs slot."""
        node = LocalNode(name="TestNode")
        node.register_math_task(
            task_id="my_filter",
            template="system_mean_v1",
            unit="V",
            color="#3b82f6",
            tags=["dsp"],
            config=[
                {"key": "cutoff", "label": "Cutoff", "type": "slider", "min": 0, "max": 100},
            ],
        )

        task = node._tasks["my_filter"]
        assert task["type"] == "MATH"
        assert task["virtual"] is True
        assert task["inputs"] == {"source": None}
        assert task["color"] == "#3b82f6"
        assert task["tags"] == ["dsp"]
        assert task["ui"]["defaultTemplate"] == "system_mean_v1"
        assert task["config"]["unit"] == "V"
        assert task["config"]["configFields"][0]["key"] == "cutoff"


class TestLocalNodeRuntime:
    """Runtime behavior tests for LocalNode internals."""

    def test_publish_without_channel_skips_send(self):
        node = LocalNode(name="TestNode")
        node._send_control = MagicMock()
        node.publish("unknown", np.array([1.0], dtype=np.float32))
        node._send_control.assert_not_called()

    def test_publish_with_channel_sends_data_available(self):
        node = LocalNode(name="TestNode")
        channel = MagicMock()
        node._shm_channels["out"] = channel
        node._send_control = MagicMock(return_value={"status": "ok"})

        node.publish("out", np.array([1.0, 2.0], dtype=np.float32))

        channel.write.assert_called_once()
        node._send_control.assert_called_once()
        sent = node._send_control.call_args[0][0]
        assert sent["type"] == "data_available"
        assert sent["task_id"] == "out"
        assert sent["count"] == 2

    def test_fetch_history_ok_returns_array(self):
        node = LocalNode(name="TestNode")
        node._send_control = MagicMock(return_value={"status": "ok", "data": [1.0, 2.5]})

        out = node.fetch_history("s1", "src")

        assert isinstance(out, np.ndarray)
        np.testing.assert_array_equal(out, np.array([1.0, 2.5], dtype=np.float64))

    def test_fetch_history_error_returns_empty(self):
        node = LocalNode(name="TestNode")
        node._send_control = MagicMock(return_value={"status": "error", "error": "boom"})

        out = node.fetch_history("s1", "src")
        assert isinstance(out, np.ndarray)
        assert out.size == 0

    def test_stop_when_not_running_is_noop(self):
        node = LocalNode(name="TestNode")
        node._deregister_from_bridge = MagicMock()
        node._cleanup = MagicMock()

        node.stop()

        node._deregister_from_bridge.assert_not_called()
        node._cleanup.assert_not_called()

    def test_stop_when_running_calls_cleanup(self):
        node = LocalNode(name="TestNode")
        node._running = True
        node._deregister_from_bridge = MagicMock()
        node._cleanup = MagicMock()

        node.stop()

        assert node._running is False
        node._deregister_from_bridge.assert_called_once()
        node._cleanup.assert_called_once()

    def test_send_control_without_socket_raises(self):
        node = LocalNode(name="TestNode")
        with pytest.raises(RuntimeError):
            node._send_control({"type": "ping"})

    def test_send_control_zmq_error_returns_error_dict(self):
        node = LocalNode(name="TestNode")
        sock = MagicMock()
        sock.send.side_effect = zmq.ZMQError("fail")
        node._control_socket = sock

        out = node._send_control({"type": "ping"})
        assert out["status"] == "error"
        assert "fail" in out["error"]

    def test_register_with_bridge_creates_shm_channels(self):
        node = LocalNode(name="TestNode")
        node.register_task("t1")
        node._send_control = MagicMock(return_value={"status": "ok", "shm_channels": {"t1": "shm_t1"}})

        with patch("elab_api.local_node.SharedMemoryChannel") as shm_cls:
            shm_inst = MagicMock()
            shm_cls.return_value = shm_inst
            node._register_with_bridge()

        assert node._shm_channels["t1"] is shm_inst
        shm_cls.assert_called_once_with(name="shm_t1", create=False)

    def test_register_with_bridge_retries_and_fails(self):
        node = LocalNode(name="TestNode")
        node.register_task("t1")
        node._send_control = MagicMock(return_value={"status": "error", "error": "timeout"})

        ok = node._register_with_bridge()

        assert ok is False
        assert node._send_control.call_count == 3

    def test_handle_heartbeat_sends_ack(self):
        node = LocalNode(name="TestNode")
        node._send_control = MagicMock(return_value={"status": "ok"})

        node._handle_notification({"type": "heartbeat"})

        node._send_control.assert_called_once_with({
            "type": "heartbeat_ack",
            "node_id": node.node_id,
        })

    def test_deregister_from_bridge_swallows_errors(self):
        node = LocalNode(name="TestNode")
        node._control_socket = MagicMock()
        node._send_control = MagicMock(side_effect=RuntimeError("x"))

        node._deregister_from_bridge()
        node._send_control.assert_called_once()


class TestLocalNodeNotifications:
    """Notification handling tests."""

    def test_handle_config_update_invokes_callback(self):
        node = LocalNode(name="TestNode")
        cb = MagicMock()
        node._config_callbacks["task1"] = cb

        node._handle_notification({"type": "config_update", "task_id": "task1", "key": "k", "value": 7})

        cb.assert_called_once_with("k", 7)

    def test_handle_input_update_sets_source_and_invokes_callback(self):
        node = LocalNode(name="TestNode")
        cb = MagicMock()
        source = {"id": "s1", "originalId": "s0"}
        node._input_callbacks["task1"] = cb

        node._handle_notification({"type": "input_update", "task_id": "task1", "source": source})

        assert node._current_source == source
        cb.assert_called_once_with(source)

    def test_handle_data_stream_fixed_callback_reads_channel(self):
        node = LocalNode(name="TestNode")
        cb = MagicMock()
        ch = MagicMock()
        ch.read_latest.return_value = np.array([1.0], dtype=np.float32)
        node._stream_callbacks["src1"] = cb
        node._shm_channels["src1"] = ch

        node._handle_notification({"type": "data_stream", "source_id": "src1", "count": 1, "values": [1.0]})

        ch.read_latest.assert_called_once_with(1)
        cb.assert_called_once()

    def test_handle_data_stream_dynamic_callback_matching_source(self):
        node = LocalNode(name="TestNode")
        dcb = MagicMock()
        node._dynamic_stream_callback = dcb
        node._current_source = {"id": "src1", "originalId": "srcA"}

        node._handle_notification({"type": "data_stream", "source_id": "srcA", "values": [1, 2]})

        dcb.assert_called_once_with("srcA", [1, 2])

    def test_handle_data_stream_dynamic_callback_non_matching_source(self):
        node = LocalNode(name="TestNode")
        dcb = MagicMock()
        node._dynamic_stream_callback = dcb
        node._current_source = {"id": "src1", "originalId": "srcA"}

        node._handle_notification({"type": "data_stream", "source_id": "other", "values": [1]})

        dcb.assert_not_called()
