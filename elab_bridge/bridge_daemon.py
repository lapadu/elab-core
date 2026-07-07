"""E-Lab Local API Bridge Daemon.

This daemon runs as an E-Lab plugin and bridges external Python scripts
(connected via ZeroMQ) to the central Socket.IO dispatcher.

Architecture:
    External Script  <--ZMQ/SHM-->  Bridge Daemon  <--Socket.IO-->  Dispatcher
"""
from __future__ import annotations

import json
import logging
import os
import signal
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

import zmq
import socketio
import numpy as np

from elab_api.shared_memory_channel import SharedMemoryChannel
from elab_clients_core.python.shared.auth import ProviderAuth

logger = logging.getLogger(__name__)

# --- Configuration ---
DEFAULT_DISPATCHER_URL = "http://127.0.0.1:5000"
ZMQ_CONTROL_PORT = 5580   # REP socket (request/reply with clients)
ZMQ_NOTIFY_PORT = 5581    # PUB socket (push notifications to clients)

# Heartbeat interval for client liveness detection (seconds)
HEARTBEAT_INTERVAL = 5.0
# Max time without heartbeat response before considering a client dead
CLIENT_TIMEOUT = 15.0

# Shared memory ring buffer capacity (samples)
SHM_CAPACITY = 65536


class ConnectedNode:
    """Represents a single connected external script."""

    def __init__(self, node_id: str, manifest: Dict[str, Any]):
        self.node_id = node_id
        self.manifest = manifest
        self.last_seen = time.time()
        self.shm_channels: Dict[str, SharedMemoryChannel] = {}

    @property
    def is_alive(self) -> bool:
        return (time.time() - self.last_seen) < CLIENT_TIMEOUT

    def touch(self) -> None:
        self.last_seen = time.time()


class BridgeDaemon:
    """The Local API Bridge Daemon.

    Manages ZMQ sockets for communication with external scripts and a
    Socket.IO connection to the E-Lab dispatcher.
    """

    def __init__(
        self,
        dispatcher_url: str = DEFAULT_DISPATCHER_URL,
        control_port: int = ZMQ_CONTROL_PORT,
        notify_port: int = ZMQ_NOTIFY_PORT,
    ):
        self._dispatcher_url = dispatcher_url
        self._control_port = control_port
        self._notify_port = notify_port

        self._nodes: Dict[str, ConnectedNode] = {}
        self._nodes_lock = threading.Lock()
        # Per-node authentication state. Each external node gets its own
        # ProviderAuth instance keyed by the node's manifest id (= device_id),
        # because credentials/secrets live per-device, not per-bridge.
        self._node_auths: Dict[str, ProviderAuth] = {}
        self._running = False

        # ZMQ context and sockets
        self._zmq_ctx: Optional[zmq.Context] = None
        self._control_socket: Optional[zmq.Socket] = None
        self._notify_socket: Optional[zmq.Socket] = None

        # Socket.IO client to the dispatcher
        self._sio: Optional[socketio.Client] = None

        # Threads
        self._control_thread: Optional[threading.Thread] = None
        self._heartbeat_thread: Optional[threading.Thread] = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the Bridge Daemon."""
        self._running = True
        self._setup_zmq()
        self._connect_dispatcher()
        self._start_threads()
        logger.info(
            "Bridge Daemon started (ctrl=%d, notify=%d, dispatcher=%s)",
            self._control_port, self._notify_port, self._dispatcher_url,
        )

    def stop(self) -> None:
        """Gracefully stop the Bridge Daemon."""
        logger.info("Stopping Bridge Daemon...")
        self._running = False

        # Deregister all nodes from dispatcher
        with self._nodes_lock:
            for node in list(self._nodes.values()):
                self._deregister_node(node)
            self._nodes.clear()

        # Disconnect Socket.IO
        if self._sio and self._sio.connected:
            try:
                self._sio.disconnect()
            except Exception:
                pass

        # Close ZMQ
        if self._control_socket:
            self._control_socket.close(linger=500)
        if self._notify_socket:
            self._notify_socket.close(linger=500)
        if self._zmq_ctx:
            self._zmq_ctx.term()

        logger.info("Bridge Daemon stopped.")

    def run_forever(self) -> None:
        """Start and block until interrupted."""
        self.start()
        try:
            while self._running:
                time.sleep(0.5)
        except KeyboardInterrupt:
            pass
        finally:
            self.stop()

    # ------------------------------------------------------------------
    # ZMQ Setup
    # ------------------------------------------------------------------

    def _setup_zmq(self) -> None:
        """Initialize ZeroMQ sockets."""
        self._zmq_ctx = zmq.Context()

        # REP socket for control plane (handles client requests)
        self._control_socket = self._zmq_ctx.socket(zmq.REP)
        self._control_socket.setsockopt(zmq.LINGER, 1000)
        self._control_socket.bind(f"tcp://*:{self._control_port}")

        # PUB socket for notifications (pushes events to clients)
        self._notify_socket = self._zmq_ctx.socket(zmq.PUB)
        self._notify_socket.setsockopt(zmq.LINGER, 1000)
        self._notify_socket.bind(f"tcp://*:{self._notify_port}")

    # ------------------------------------------------------------------
    # Socket.IO (Dispatcher Connection)
    # ------------------------------------------------------------------

    def _connect_dispatcher(self) -> None:
        """Connect to the E-Lab dispatcher via Socket.IO."""
        self._sio = socketio.Client(
            reconnection=True,
            reconnection_delay=2,
            reconnection_delay_max=30,
            logger=False,
        )

        @self._sio.on("connect")
        def on_connect():
            logger.info("Connected to E-Lab dispatcher at %s", self._dispatcher_url)
            # Join ui_clients room so we receive data_stream broadcasts
            self._sio.emit("register_client", {"type": "bridge"})

        @self._sio.on("disconnect")
        def on_disconnect():
            logger.warning("Disconnected from E-Lab dispatcher.")

        @self._sio.on("update_config")
        def on_update_config(data):
            """Forward config updates from the dispatcher to the target node."""
            self._forward_config_update(data)

        @self._sio.on("execute_command")
        def on_execute_command(data):
            """Forward execute_command (update_input, update_config, update_meta)."""
            self._forward_execute_command(data)

        @self._sio.on("data_stream")
        def on_data_stream(data):
            """Forward incoming stream data to subscribed nodes."""
            self._forward_stream_data(data)

        # --- Provider pairing events (one socket, many proxied devices) ----
        @self._sio.on("registration_approved")
        def on_registration_approved(data):
            if not isinstance(data, dict):
                return
            device_id = data.get("deviceId")
            secret = data.get("secret")
            if not isinstance(device_id, str) or not isinstance(secret, str):
                return
            auth = self._node_auths.get(device_id)
            if auth is None:
                logger.warning("registration_approved for unknown device_id %s", device_id)
                return
            # Inject the secret via the same code path the real client uses.
            with auth._lock:  # pylint: disable=protected-access
                auth._secret_hex = secret  # pylint: disable=protected-access
            auth._save_secret(secret)      # pylint: disable=protected-access
            auth._approved.set()           # pylint: disable=protected-access
            logger.info("✅ Bridge: device %s approved by dispatcher", device_id)

        @self._sio.on("registration_pending")
        def on_registration_pending(data):
            logger.info("⏳ Bridge: device pending operator approval: %r", data)

        @self._sio.on("registration_revoked")
        def on_registration_revoked(data):
            if not isinstance(data, dict):
                return
            device_id = data.get("deviceId")
            if not isinstance(device_id, str):
                return
            auth = self._node_auths.pop(device_id, None)
            if auth is not None:
                auth.forget()
            logger.warning("⛔ Bridge: device %s credential revoked", device_id)

        try:
            self._sio.connect(self._dispatcher_url, wait_timeout=10)
        except socketio.exceptions.ConnectionError as exc:
            logger.error("Cannot connect to dispatcher: %s", exc)
            raise

    # ------------------------------------------------------------------
    # Thread Management
    # ------------------------------------------------------------------

    def _start_threads(self) -> None:
        """Start background threads for control loop and heartbeat."""
        self._control_thread = threading.Thread(
            target=self._control_loop, daemon=True, name="bridge_control"
        )
        self._control_thread.start()

        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop, daemon=True, name="bridge_heartbeat"
        )
        self._heartbeat_thread.start()

    # ------------------------------------------------------------------
    # Control Plane (ZMQ REQ/REP)
    # ------------------------------------------------------------------

    def _control_loop(self) -> None:
        """Main loop processing control requests from connected nodes."""
        poller = zmq.Poller()
        poller.register(self._control_socket, zmq.POLLIN)

        while self._running:
            try:
                events = dict(poller.poll(timeout=500))
            except zmq.ZMQError:
                break

            if self._control_socket not in events:
                continue

            try:
                raw = self._control_socket.recv()
                msg = json.loads(raw.decode("utf-8"))
                response = self._handle_control_message(msg)
                self._control_socket.send(
                    json.dumps(response).encode("utf-8")
                )
            except zmq.ZMQError as exc:
                logger.error("ZMQ control error: %s", exc)
                break
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                logger.warning("Invalid control message: %s", exc)
                try:
                    self._control_socket.send(
                        json.dumps({"status": "error", "error": "invalid message"}).encode("utf-8")
                    )
                except zmq.ZMQError:
                    break

    def _handle_control_message(self, msg: Dict[str, Any]) -> Dict[str, Any]:
        """Route a control-plane message to the appropriate handler."""
        msg_type = msg.get("type")

        if msg_type == "register":
            return self._handle_register(msg)
        elif msg_type == "deregister":
            return self._handle_deregister(msg)
        elif msg_type == "data_available":
            return self._handle_data_available(msg)
        elif msg_type == "actor_command":
            return self._handle_actor_command(msg)
        elif msg_type == "fetch_history":
            return self._handle_fetch_history(msg)
        elif msg_type == "heartbeat_ack":
            return self._handle_heartbeat_ack(msg)
        else:
            return {"status": "error", "error": f"unknown message type: {msg_type}"}

    def _handle_register(self, msg: Dict[str, Any]) -> Dict[str, Any]:
        """Register a new external node and forward its manifest to the dispatcher."""
        manifest = msg.get("manifest")
        if not manifest or not isinstance(manifest, dict):
            return {"status": "error", "error": "missing or invalid manifest"}

        node_id = manifest.get("id")
        if not node_id:
            return {"status": "error", "error": "manifest missing 'id'"}

        # If the same node re-registers (e.g. after a request timeout),
        # release old SHM resources before replacing it.
        with self._nodes_lock:
            existing = self._nodes.pop(node_id, None)
        if existing:
            logger.warning("Node '%s' re-registering; replacing previous instance.", node_id)
            self._deregister_node(existing)

        node = ConnectedNode(node_id=node_id, manifest=manifest)

        # Create shared memory channels for each task
        shm_info: Dict[str, str] = {}
        for task in manifest.get("tasks", []):
            task_id = task.get("id")
            if task_id:
                shm_name = f"elab_shm_{node_id}_{task_id}_{uuid.uuid4().hex[:6]}"
                try:
                    channel = SharedMemoryChannel(
                        name=shm_name,
                        capacity=SHM_CAPACITY,
                        create=True,
                    )
                    node.shm_channels[task_id] = channel
                    shm_info[task_id] = shm_name
                except (OSError, ValueError) as exc:
                    logger.error("Failed to create SHM for %s: %s", task_id, exc)

        # Store the node
        with self._nodes_lock:
            self._nodes[node_id] = node

        # Set up per-node authentication state, then forward registration.
        auth = self._node_auths.get(node_id)
        if auth is None:
            auth = ProviderAuth(device_id=node_id)
            self._node_auths[node_id] = auth

        # Forward registration to the dispatcher
        try:
            assert self._sio is not None
            auth.send_register(self._sio, manifest)
            logger.info("Registered node '%s' with dispatcher.", node_id)
        except Exception as exc:  # pylint: disable=broad-except
            logger.error("Failed to register with dispatcher: %s", exc)
            return {"status": "error", "error": str(exc)}

        return {"status": "ok", "shm_channels": shm_info}

    def _handle_deregister(self, msg: Dict[str, Any]) -> Dict[str, Any]:
        """Deregister a node and clean up resources."""
        node_id = msg.get("node_id")
        if not node_id:
            return {"status": "error", "error": "missing node_id"}

        with self._nodes_lock:
            node = self._nodes.pop(node_id, None)

        if node:
            self._deregister_node(node)
            return {"status": "ok"}
        return {"status": "error", "error": "node not found"}

    def _handle_data_available(self, msg: Dict[str, Any]) -> Dict[str, Any]:
        """Handle notification that a node has written new data to SHM."""
        task_id = msg.get("task_id")
        count = msg.get("count", 0)
        timestamp_ns = msg.get("timestamp_ns", time.time_ns())

        # Find the node and its SHM channel
        node_id = msg.get("source_node") or self._find_node_for_task(task_id)
        if not node_id:
            return {"status": "error", "error": "task not found"}

        with self._nodes_lock:
            node = self._nodes.get(node_id)
        if not node:
            return {"status": "error", "error": "node not found"}

        channel = node.shm_channels.get(task_id)
        if not channel:
            return {"status": "error", "error": "no shm channel for task"}

        node.touch()

        # Read the data from SHM and forward to dispatcher
        data = channel.read_latest(count)
        if len(data) > 0:
            payload = {
                # Dispatcher expects camelCase sourceId on inbound data_stream.
                "sourceId": task_id,
                "values": data.tolist(),
                "timestamp": timestamp_ns / 1e9,
            }
            auth = self._node_auths.get(node_id)
            if auth is None or not auth.has_secret():
                # Not yet approved by operator; drop instead of sending an
                # unsigned packet (which would be rejected anyway).
                logger.debug("Dropping data_stream from unapproved node %s", node_id)
                return {"status": "ok", "dropped": True}
            assert self._sio is not None
            self._sio.emit("data_stream", auth.sign(payload))

        return {"status": "ok"}

    def _handle_actor_command(self, msg: Dict[str, Any]) -> Dict[str, Any]:
        """Forward an actor command to the dispatcher."""
        target = msg.get("target_task_id")
        action = msg.get("action")
        payload = msg.get("payload", {})

        if not target or not action:
            return {"status": "error", "error": "missing target_task_id or action"}

        self._sio.emit("update_config", {
            "target_task_id": target,
            "action": action,
            "payload": payload,
        })
        return {"status": "ok"}

    def _handle_fetch_history(self, msg: Dict[str, Any]) -> Dict[str, Any]:
        """Fetch historical data from recorded sessions."""
        session_id = msg.get("session_id")
        source_id = msg.get("source_id")

        if not session_id or not source_id:
            return {"status": "error", "error": "missing session_id or source_id"}

        # Read data from the session SQLite database
        import sqlite3
        from elab_server.config import SESSION_DIR

        session_dir = os.path.join(SESSION_DIR, session_id)
        db_path = os.path.join(session_dir, "session.sqlite")

        if not os.path.isfile(db_path):
            return {"status": "error", "error": f"session '{session_id}' not found"}

        try:
            conn = sqlite3.connect(db_path, timeout=5)
            cursor = conn.cursor()

            query = "SELECT value FROM stream_data WHERE source_id = ?"
            params: list = [source_id]

            start_time = msg.get("start_time")
            end_time = msg.get("end_time")
            if start_time is not None:
                query += " AND timestamp >= ?"
                params.append(start_time)
            if end_time is not None:
                query += " AND timestamp <= ?"
                params.append(end_time)

            query += " ORDER BY timestamp ASC"
            cursor.execute(query, params)
            rows = cursor.fetchall()
            conn.close()

            values = [row[0] for row in rows if row[0] is not None]
            return {"status": "ok", "data": values}
        except (sqlite3.Error, OSError) as exc:
            return {"status": "error", "error": str(exc)}

    def _handle_heartbeat_ack(self, msg: Dict[str, Any]) -> Dict[str, Any]:
        """Process a heartbeat acknowledgement from a client."""
        node_id = msg.get("node_id")
        if node_id:
            with self._nodes_lock:
                node = self._nodes.get(node_id)
                if node:
                    node.touch()
        return {"status": "ok"}

    # ------------------------------------------------------------------
    # Notification Forwarding (Dispatcher -> Nodes)
    # ------------------------------------------------------------------

    def _forward_config_update(self, data: Dict[str, Any]) -> None:
        """Forward a config update from the dispatcher to the target node."""
        task_id = data.get("target_task_id") or data.get("task_id")
        if not task_id:
            return

        node_id = self._find_node_for_task(task_id)
        if not node_id:
            return

        # Publish via ZMQ PUB socket
        payload = json.dumps({
            "type": "config_update",
            "task_id": task_id,
            "key": data.get("key"),
            "value": data.get("value"),
        }).encode("utf-8")

        try:
            self._notify_socket.send_multipart([
                node_id.encode("utf-8"),
                payload,
            ])
        except zmq.ZMQError as exc:
            logger.error("Failed to forward config_update: %s", exc)

    def _forward_execute_command(self, data: Dict[str, Any]) -> None:
        """Forward execute_command events (update_input, update_config, update_meta).

        These are emitted by the frontend when the user drags a source
        onto a MATH widget or changes configuration.
        """
        provider_id = data.get("provider_id")
        command = data.get("command", {})
        action = command.get("action")

        if not provider_id or not action:
            return

        # provider_id is "prov_<task_originalId>" – extract the task id
        task_id = provider_id.removeprefix("prov_") if provider_id.startswith("prov_") else provider_id
        node_id = self._find_node_for_task(task_id)
        if not node_id:
            return

        if action == "update_input":
            source = command.get("payload", {}).get("source")
            payload = json.dumps({
                "type": "input_update",
                "task_id": task_id,
                "source": source,
            }).encode("utf-8")
        elif action == "update_config":
            payload = json.dumps({
                "type": "config_update",
                "task_id": task_id,
                **{k: v for k, v in command.get("payload", {}).items()},
            }).encode("utf-8")
        elif action == "update_meta":
            payload = json.dumps({
                "type": "meta_update",
                "task_id": task_id,
                **command.get("payload", {}),
            }).encode("utf-8")
        else:
            return

        try:
            self._notify_socket.send_multipart([
                node_id.encode("utf-8"),
                payload,
            ])
        except zmq.ZMQError as exc:
            logger.error("Failed to forward execute_command (%s): %s", action, exc)

    def _forward_stream_data(self, data: Dict[str, Any]) -> None:
        """Forward stream data from the dispatcher to subscribed nodes."""
        source_id = data.get("source_id") or data.get("sourceId")
        if not source_id:
            return

        values = data.get("values", [])
        value = data.get("value")

        # Build lightweight notification with inline values
        msg: Dict[str, Any] = {
            "type": "data_stream",
            "source_id": source_id,
        }
        if values:
            msg["values"] = values
        elif value is not None:
            msg["values"] = [value]
        else:
            return

        payload = json.dumps(msg).encode("utf-8")

        try:
            self._notify_socket.send_multipart([
                b"broadcast",
                payload,
            ])
        except zmq.ZMQError as exc:
            logger.error("Failed to forward stream_data: %s", exc)

    # ------------------------------------------------------------------
    # Heartbeat & Garbage Collection
    # ------------------------------------------------------------------

    def _heartbeat_loop(self) -> None:
        """Periodically check client liveness and clean up orphaned resources."""
        while self._running:
            time.sleep(HEARTBEAT_INTERVAL)

            dead_nodes: List[str] = []
            with self._nodes_lock:
                for node_id, node in self._nodes.items():
                    if not node.is_alive:
                        dead_nodes.append(node_id)
                    else:
                        # Send heartbeat probe
                        try:
                            payload = json.dumps({"type": "heartbeat"}).encode("utf-8")
                            self._notify_socket.send_multipart([
                                node_id.encode("utf-8"),
                                payload,
                            ])
                        except zmq.ZMQError:
                            pass

            # Clean up dead nodes
            for node_id in dead_nodes:
                logger.warning("Node '%s' timed out. Cleaning up.", node_id)
                with self._nodes_lock:
                    node = self._nodes.pop(node_id, None)
                if node:
                    self._deregister_node(node)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _find_node_for_task(self, task_id: str) -> Optional[str]:
        """Find which node owns a given task_id."""
        with self._nodes_lock:
            for node_id, node in self._nodes.items():
                for task in node.manifest.get("tasks", []):
                    if task.get("id") == task_id:
                        return node_id
        return None

    def _deregister_node(self, node: ConnectedNode) -> None:
        """Clean up a node: release SHM and notify the dispatcher."""
        # Clean up shared memory
        for channel in node.shm_channels.values():
            channel.close()
            channel.unlink()
        node.shm_channels.clear()

        # Notify dispatcher about the provider going offline
        # (The dispatcher handles this via disconnect, but we emit explicitly
        #  if we're still connected.)
        if self._sio and self._sio.connected:
            try:
                self._sio.emit("deregister_provider", {
                    "provider_id": node.node_id,
                })
            except Exception:
                pass

        logger.info("Node '%s' deregistered and resources freed.", node.node_id)


# ------------------------------------------------------------------
# Entry Point
# ------------------------------------------------------------------

def main() -> None:
    """Run the Bridge Daemon as a standalone process."""
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    parser = argparse.ArgumentParser(description="E-Lab Local API Bridge Daemon")
    parser.add_argument(
        "--dispatcher-url",
        default=os.environ.get("ELAB_DISPATCHER_URL", DEFAULT_DISPATCHER_URL),
        help="URL of the E-Lab dispatcher (default: %(default)s)",
    )
    parser.add_argument(
        "--control-port", type=int, default=ZMQ_CONTROL_PORT,
        help="ZMQ control port (default: %(default)s)",
    )
    parser.add_argument(
        "--notify-port", type=int, default=ZMQ_NOTIFY_PORT,
        help="ZMQ notify port (default: %(default)s)",
    )
    args = parser.parse_args()

    daemon = BridgeDaemon(
        dispatcher_url=args.dispatcher_url,
        control_port=args.control_port,
        notify_port=args.notify_port,
    )

    signal.signal(signal.SIGINT, lambda *_: daemon.stop())
    signal.signal(signal.SIGTERM, lambda *_: daemon.stop())

    daemon.run_forever()


if __name__ == "__main__":
    main()
