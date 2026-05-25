"""LocalNode – the primary user-facing class for external scripts.

Connects to the Bridge Daemon via ZeroMQ and optionally subscribes to
shared memory data channels.
"""
from __future__ import annotations

import atexit
import json
import logging
import signal
import threading
import time
import uuid
from typing import Any, Callable, Dict, List, Optional

import numpy as np
import zmq

from .shared_memory_channel import SharedMemoryChannel

logger = logging.getLogger(__name__)

# Default ZMQ ports used by the Bridge Daemon
_DEFAULT_CONTROL_PORT = 5580
_DEFAULT_NOTIFY_PORT = 5581
_CONTROL_SOCKET_TIMEOUT_MS = 10000
_REGISTER_MAX_ATTEMPTS = 3
_REGISTER_RETRY_DELAY_S = 0.5


class LocalNode:
    """Lightweight client that connects an external script to the E-Lab Bridge.

    Parameters
    ----------
    name : str
        Human-readable name for this node (shown in the UI).
    bridge_host : str
        Hostname of the Bridge Daemon (default: localhost).
    control_port : int
        ZMQ REQ/REP port on the Bridge (default: 5580).
    notify_port : int
        ZMQ PUB/SUB port for async notifications from the Bridge (default: 5581).
    """

    def __init__(
        self,
        name: str,
        bridge_host: str = "127.0.0.1",
        control_port: int = _DEFAULT_CONTROL_PORT,
        notify_port: int = _DEFAULT_NOTIFY_PORT,
    ):
        self.name = name
        self.node_id = f"local_node_{uuid.uuid4().hex[:8]}"
        self._bridge_host = bridge_host
        self._control_port = control_port
        self._notify_port = notify_port

        self._tasks: Dict[str, Dict[str, Any]] = {}
        self._config_callbacks: Dict[str, Callable] = {}
        self._input_callbacks: Dict[str, Callable] = {}
        self._stream_callbacks: Dict[str, Callable] = {}
        self._dynamic_stream_callback: Optional[Callable] = None
        self._current_source: Optional[Dict[str, Any]] = None
        self._shm_channels: Dict[str, SharedMemoryChannel] = {}

        self._running = False
        self._zmq_ctx: Optional[zmq.Context] = None
        self._control_socket: Optional[zmq.Socket] = None
        self._notify_socket: Optional[zmq.Socket] = None
        self._notify_thread: Optional[threading.Thread] = None
        self._control_lock = threading.Lock()

        # Cleanup on exit
        atexit.register(self._cleanup)
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def register_task(
        self,
        task_id: str,
        task_type: str = "SENSOR",
        template: str = "tpl_generic_sensor",
        config: Optional[List[Dict[str, Any]]] = None,
        name: Optional[str] = None,
        color: Optional[str] = None,
        tags: Optional[List[str]] = None,
        unit: Optional[str] = None,
        sample_rate: Optional[int] = None,
        ui_mode: str = "generic",
        ui_url: Optional[str] = None,
        ui_component_name: Optional[str] = None,
        ui_integrity: Optional[str] = None,
    ) -> None:
        """Register a task with the E-Lab dispatcher via the Bridge.

        Parameters
        ----------
        task_id : str
            Unique identifier for this task.
        task_type : str
            E-Lab task type (SENSOR, ACTUATOR, MATH, MEASURE, CONTROL, GENERATOR).
        template : str
            Frontend template ID (e.g. ``tpl_generic_sensor``, ``tpl_metric``).
        config : list[dict], optional
            Array of configFields conforming to the E-Lab schema. These are
            passed verbatim to generate the DeviceConfigWidget in the UI.
        name : str, optional
            Display name. Defaults to *task_id*.
        color : str, optional
            Default hex color (e.g. ``#ef4444``).
        tags : list[str], optional
            Freeform tags for UI filtering.
        unit : str, optional
            Measurement unit.
        sample_rate : int, optional
            Expected sample rate in samples/s.
        ui_mode : str
            ``generic`` or ``custom``.
        ui_url : str, optional
            URL to custom JS plugin (mode=custom).
        ui_component_name : str, optional
            React component name (mode=custom).
        ui_integrity : str, optional
            SRI hash for the plugin script.
        """
        task_def: Dict[str, Any] = {
            "id": task_id,
            "name": name or task_id,
            "type": task_type,
            "ui": {
                "mode": ui_mode,
                "template": template,
            },
        }

        if color:
            task_def["color"] = color
        if tags:
            task_def["tags"] = tags

        # Build config object
        task_config: Dict[str, Any] = {}
        if unit:
            task_config["unit"] = unit
        if sample_rate is not None:
            task_config["sampleRate"] = sample_rate
        if config:
            task_config["configFields"] = config
        if task_config:
            task_def["config"] = task_config

        # Custom UI fields
        if ui_mode == "custom":
            if ui_url:
                task_def["ui"]["url"] = ui_url
            if ui_component_name:
                task_def["ui"]["componentName"] = ui_component_name
            if ui_integrity:
                task_def["ui"]["integrity"] = ui_integrity

        self._tasks[task_id] = task_def
        logger.info("Task '%s' registered locally. Will sync on run().", task_id)

    def register_math_task(
        self,
        task_id: str,
        template: str = "system_mean_v1",
        config: Optional[List[Dict[str, Any]]] = None,
        name: Optional[str] = None,
        color: Optional[str] = None,
        tags: Optional[List[str]] = None,
        unit: Optional[str] = None,
    ) -> None:
        """Register a MATH task with an input slot (like Mean).

        The task appears in the UI with a drop zone where the user can
        drag any Sensor or Generator as input source.  When the user
        assigns a source, the ``on_input_update`` callback fires and
        ``on_stream`` begins receiving data from that source.

        Parameters
        ----------
        task_id : str
            Unique identifier for this task.
        template : str
            Frontend template ID (default: ``system_mean_v1``).
        config : list[dict], optional
            Array of configFields for the DeviceConfigWidget.
        name : str, optional
            Display name. Defaults to *task_id*.
        color : str, optional
            Default hex color.
        tags : list[str], optional
            Freeform tags.
        unit : str, optional
            Measurement unit.
        """
        task_def: Dict[str, Any] = {
            "id": task_id,
            "name": name or task_id,
            "type": "MATH",
            "virtual": True,
            "inputs": {"source": None},
            "color": color or "#06b6d4",
            "ui": {
                "mode": "generic",
                "defaultTemplate": template,
                "views": [
                    {
                        "id": "config",
                        "label": "Konfig",
                        "icon": "Settings",
                        "template": template,
                    }
                ],
            },
        }
        if tags:
            task_def["tags"] = tags

        task_config: Dict[str, Any] = {}
        if unit:
            task_config["unit"] = unit
            task_config["factor"] = 1.0
        if config:
            task_config["configFields"] = config
        if task_config:
            task_def["config"] = task_config

        self._tasks[task_id] = task_def
        logger.info("MATH task '%s' registered (template=%s).", task_id, template)

    def on_config_update(self, task_id: str) -> Callable:
        """Decorator to register a callback for config changes from the UI.

        Usage::

            @node.on_config_update("filtered_signal")
            def update_params(key, value):
                ...
        """
        def decorator(func: Callable) -> Callable:
            self._config_callbacks[task_id] = func
            return func
        return decorator

    def on_input_update(self, task_id: str) -> Callable:
        """Decorator for when the user assigns/removes an input source in the UI.

        The callback receives the source dict (or None when cleared).

        Usage::

            @node.on_input_update("filtered_signal")
            def source_changed(source):
                print(f"New source: {source}")
        """
        def decorator(func: Callable) -> Callable:
            self._input_callbacks[task_id] = func
            return func
        return decorator

    def on_stream(self, source_id: str) -> Callable:
        """Decorator to register a callback for data from a fixed source.

        The callback receives a NumPy array of samples.

        Usage::

            @node.on_stream("esp32_voltmeter_raw")
            def process(data_chunk: np.ndarray):
                ...
        """
        def decorator(func: Callable) -> Callable:
            self._stream_callbacks[source_id] = func
            return func
        return decorator

    def on_dynamic_stream(self) -> Callable:
        """Decorator for data from whichever source the UI currently assigns.

        Automatically follows ``update_input`` changes.  The callback
        receives ``(source_id, values)``.

        Usage::

            @node.on_dynamic_stream()
            def process(source_id: str, values: list):
                ...
        """
        def decorator(func: Callable) -> Callable:
            self._dynamic_stream_callback = func
            return func
        return decorator

    def publish(self, task_id: str, data: np.ndarray) -> None:
        """Publish data for a task via shared memory.

        Parameters
        ----------
        task_id : str
            The task whose data channel to write to.
        data : np.ndarray
            Samples to publish.
        """
        channel = self._shm_channels.get(task_id)
        if channel is None:
            logger.warning("No shared memory channel for task '%s'. Skipping.", task_id)
            return
        channel.write(data)
        # Notify the bridge that new data is available
        self._send_control({
            "type": "data_available",
            "task_id": task_id,
            "count": len(data),
            "timestamp_ns": time.time_ns(),
        })

    def send_command(self, target_task_id: str, action: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Send an actor command through the bridge to another task.

        Parameters
        ----------
        target_task_id : str
            The task to command.
        action : str
            Command action key.
        payload : dict, optional
            Additional command data.

        Returns
        -------
        dict
            Response from the bridge.
        """
        msg = {
            "type": "actor_command",
            "target_task_id": target_task_id,
            "action": action,
            "payload": payload or {},
            "source_node": self.node_id,
        }
        return self._send_control(msg)

    def fetch_history(
        self,
        session_id: str,
        source_id: str,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None,
    ) -> np.ndarray:
        """Fetch historical session data as a NumPy array.

        Parameters
        ----------
        session_id : str
            Recorded session identifier.
        source_id : str
            The source/task to retrieve data for.
        start_time : float, optional
            Start timestamp filter.
        end_time : float, optional
            End timestamp filter.

        Returns
        -------
        np.ndarray
            Aggregated measurement values.
        """
        resp = self._send_control({
            "type": "fetch_history",
            "session_id": session_id,
            "source_id": source_id,
            "start_time": start_time,
            "end_time": end_time,
        })
        if resp.get("status") == "ok" and "data" in resp:
            return np.array(resp["data"], dtype=np.float64)
        logger.error("fetch_history failed: %s", resp.get("error", "unknown"))
        return np.empty(0, dtype=np.float64)

    def run(self) -> None:
        """Start the node, connect to the bridge, and enter the event loop.

        Blocks until SIGINT/SIGTERM or ``stop()`` is called.
        """
        self._running = True
        self._connect()
        if not self._register_with_bridge():
            logger.error("LocalNode registration failed; stopping.")
            self._running = False
            self._cleanup()
            return
        self._start_notify_listener()

        logger.info("LocalNode '%s' running. Press Ctrl+C to stop.", self.name)
        try:
            while self._running:
                time.sleep(0.1)
        except KeyboardInterrupt:
            pass
        finally:
            self.stop()

    def stop(self) -> None:
        """Gracefully disconnect and release resources."""
        if not self._running:
            return
        self._running = False
        self._deregister_from_bridge()
        self._cleanup()
        logger.info("LocalNode '%s' stopped.", self.name)

    # ------------------------------------------------------------------
    # Internal: ZMQ Communication
    # ------------------------------------------------------------------

    def _connect(self) -> None:
        """Establish ZMQ connections to the Bridge Daemon."""
        self._zmq_ctx = zmq.Context()

        # REQ/REP for control messages
        self._control_socket = self._zmq_ctx.socket(zmq.REQ)
        self._control_socket.setsockopt(zmq.RCVTIMEO, _CONTROL_SOCKET_TIMEOUT_MS)
        self._control_socket.setsockopt(zmq.SNDTIMEO, _CONTROL_SOCKET_TIMEOUT_MS)
        self._control_socket.setsockopt(zmq.LINGER, 1000)
        self._control_socket.connect(
            f"tcp://{self._bridge_host}:{self._control_port}"
        )

        # SUB for async notifications (config updates, stream data)
        self._notify_socket = self._zmq_ctx.socket(zmq.SUB)
        self._notify_socket.setsockopt(zmq.LINGER, 0)
        self._notify_socket.connect(
            f"tcp://{self._bridge_host}:{self._notify_port}"
        )
        # Subscribe to messages for this node
        self._notify_socket.setsockopt_string(zmq.SUBSCRIBE, self.node_id)
        # Subscribe to broadcast messages
        self._notify_socket.setsockopt_string(zmq.SUBSCRIBE, "broadcast")

        logger.info(
            "Connected to Bridge at %s (ctrl=%d, notify=%d)",
            self._bridge_host, self._control_port, self._notify_port,
        )

    def _send_control(self, msg: Dict[str, Any]) -> Dict[str, Any]:
        """Send a request on the control plane and return the reply."""
        if self._control_socket is None:
            raise RuntimeError("Not connected to Bridge Daemon.")
        try:
            payload = json.dumps(msg).encode("utf-8")
            with self._control_lock:
                self._control_socket.send(payload)
                reply = self._control_socket.recv()
            return json.loads(reply.decode("utf-8"))
        except zmq.ZMQError as exc:
            logger.error("ZMQ control error: %s", exc)
            return {"status": "error", "error": str(exc)}

    def _register_with_bridge(self) -> bool:
        """Send the full manifest to the Bridge for dispatcher registration."""
        manifest = {
            "id": self.node_id,
            "name": self.name,
            "category": "VIRTUAL_SCRIPT",
            "providerVersion": "1.0.0",
            "apiVersion": "2.0.0",
            "persistConfig": False,
            "tasks": list(self._tasks.values()),
        }
        for attempt in range(1, _REGISTER_MAX_ATTEMPTS + 1):
            resp = self._send_control({
                "type": "register",
                "manifest": manifest,
            })
            if resp.get("status") == "ok":
                logger.info("Successfully registered with Bridge Daemon.")
                # Set up shared memory channels for output tasks
                shm_info = resp.get("shm_channels", {})
                for task_id, channel_name in shm_info.items():
                    self._shm_channels[task_id] = SharedMemoryChannel(
                        name=channel_name, create=False
                    )
                return True

            logger.warning(
                "Registration attempt %d/%d failed: %s",
                attempt,
                _REGISTER_MAX_ATTEMPTS,
                resp.get("error", "unknown"),
            )
            if attempt < _REGISTER_MAX_ATTEMPTS:
                time.sleep(_REGISTER_RETRY_DELAY_S)

        logger.error("Registration failed after %d attempts.", _REGISTER_MAX_ATTEMPTS)
        return False

    def _deregister_from_bridge(self) -> None:
        """Notify the bridge that this node is shutting down."""
        if self._control_socket is None:
            return
        try:
            self._send_control({
                "type": "deregister",
                "node_id": self.node_id,
            })
        except (zmq.ZMQError, RuntimeError):
            pass

    def _start_notify_listener(self) -> None:
        """Start a background thread listening for PUB/SUB notifications."""
        self._notify_thread = threading.Thread(
            target=self._notify_loop, daemon=True, name="elab_api_notify"
        )
        self._notify_thread.start()

    def _notify_loop(self) -> None:
        """Background loop processing incoming notifications from the bridge."""
        poller = zmq.Poller()
        poller.register(self._notify_socket, zmq.POLLIN)

        while self._running:
            try:
                events = dict(poller.poll(timeout=200))
            except zmq.ZMQError:
                break

            if self._notify_socket in events:
                try:
                    raw = self._notify_socket.recv_multipart()
                    if len(raw) < 2:
                        continue
                    # raw[0] = topic, raw[1] = payload
                    payload = json.loads(raw[1].decode("utf-8"))
                    self._handle_notification(payload)
                except (zmq.ZMQError, json.JSONDecodeError, IndexError) as exc:
                    logger.debug("Notification parse error: %s", exc)

    def _handle_notification(self, payload: Dict[str, Any]) -> None:
        """Dispatch an incoming notification to the appropriate callback."""
        msg_type = payload.get("type")

        if msg_type == "config_update":
            task_id = payload.get("task_id")
            key = payload.get("key")
            value = payload.get("value")
            cb = self._config_callbacks.get(task_id)
            if cb and key is not None:
                try:
                    cb(key, value)
                except Exception:
                    logger.exception("Error in config_update callback for '%s'", task_id)

        elif msg_type == "input_update":
            task_id = payload.get("task_id")
            source = payload.get("source")
            self._current_source = source
            cb = self._input_callbacks.get(task_id)
            if cb:
                try:
                    cb(source)
                except Exception:
                    logger.exception("Error in input_update callback for '%s'", task_id)

        elif msg_type == "data_stream":
            source_id = payload.get("source_id")
            values = payload.get("values", [])

            # Fixed stream callbacks
            cb = self._stream_callbacks.get(source_id)
            if cb:
                channel = self._shm_channels.get(source_id)
                if channel:
                    count = payload.get("count", 1)
                    data = channel.read_latest(count)
                    try:
                        cb(data)
                    except Exception:
                        logger.exception("Error in stream callback for '%s'", source_id)

            # Dynamic stream: follows whichever source the UI assigned
            if self._dynamic_stream_callback and self._current_source:
                cur_ids = [self._current_source.get("id"),
                           self._current_source.get("originalId")]
                if source_id in [x for x in cur_ids if x]:
                    try:
                        self._dynamic_stream_callback(source_id, values)
                    except Exception:
                        logger.exception("Error in dynamic stream callback")

        elif msg_type == "heartbeat":
            # Respond to keep-alive probes from bridge.
            try:
                self._send_control({
                    "type": "heartbeat_ack",
                    "node_id": self.node_id,
                })
            except RuntimeError:
                logger.debug("Skipping heartbeat ack while control socket is unavailable.")

    # ------------------------------------------------------------------
    # Cleanup & Signal Handling
    # ------------------------------------------------------------------

    def _signal_handler(self, signum: int, frame: Any) -> None:
        """Handle SIGINT/SIGTERM for graceful shutdown."""
        logger.info("Signal %d received, shutting down...", signum)
        self._running = False

    def _cleanup(self) -> None:
        """Release ZMQ sockets and shared memory."""
        # Close shared memory channels
        for channel in self._shm_channels.values():
            channel.close()
        self._shm_channels.clear()

        # Close ZMQ sockets
        if self._control_socket:
            try:
                self._control_socket.close(linger=0)
            except zmq.ZMQError:
                pass
            self._control_socket = None

        if self._notify_socket:
            try:
                self._notify_socket.close(linger=0)
            except zmq.ZMQError:
                pass
            self._notify_socket = None

        if self._zmq_ctx:
            try:
                self._zmq_ctx.term()
            except zmq.ZMQError:
                pass
            self._zmq_ctx = None
