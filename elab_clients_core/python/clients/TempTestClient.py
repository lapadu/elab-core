# pylint: disable=invalid-name
"""
E-Lab client that simulates a simple temperature sensor.
"""

import time
import math
import random
import logging
import sys
import threading
import signal
from typing import Any

import os

project_root = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)
sys.path.append(project_root)
# Add the client directory as an import root for the shared-module fallback.
_clients_dir = os.path.dirname(os.path.abspath(__file__))
if _clients_dir not in sys.path:
    sys.path.insert(0, _clients_dir)
# Add the python/ parent directory so ``from shared.X import …`` works when
# the client is launched directly from elab_clients_core/python/clients/.
_python_dir = os.path.dirname(_clients_dir)
if _python_dir not in sys.path:
    sys.path.insert(0, _python_dir)

import socketio


def discover_dispatcher(*_args: Any, **_kwargs: Any) -> str | None:
    """Fallback discovery function replaced by shared import when available."""
    return None


try:
    # Preferred: absolute import that always resolves when the project root
    # is on sys.path (server-spawned and dev workflows).
    from elab_clients_core.python.shared.discovery import discover_dispatcher  # type: ignore[import-not-found]
    from elab_clients_core.python.shared.overrides import (  # type: ignore[import-not-found]
        load_overrides,
        save_overrides,
        apply_task_meta_update,
    )
    from elab_clients_core.python.shared.auth import ProviderAuth  # type: ignore[import-not-found]
except ImportError:
    # Fallback: launched from the clients dir (e.g. Raspberry Pi packaging
    # that ships the shared modules next to the script). ``_python_dir`` is
    # on sys.path above so ``from shared.X import …`` resolves cleanly.
    from shared.discovery import discover_dispatcher  # type: ignore[import-not-found]
    from shared.overrides import (  # type: ignore[import-not-found]
        load_overrides,
        save_overrides,
        apply_task_meta_update,
    )
    from shared.auth import ProviderAuth  # type: ignore[import-not-found]
from elab_server.manifest_builder import (
    ManifestBuilder,
)

# --- CONFIGURATION ---
UDP_PORT = 5005
SENSOR_ID = "hw_temp_sensor"
SENSOR_NAME = "Thermo-Sensor"

# --- LOGGING ---
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(SENSOR_NAME)

sio: Any = None

# pylint: disable=C0301

# --- DEFAULT MANIFEST ---
builder = ManifestBuilder(SENSOR_ID, SENSOR_NAME)
builder.add_task(
    task_id=f"{SENSOR_ID}_task",
    name="Temperatur Kanal 1",
    task_type="SENSOR",
    group_id="plugin_volt_v1",
    virtual=False,
    color="#ef4444",
    tags=["Temp", "CPU", "Test"],
    config={
        "range": [0, 30],
        "unit": "°C",
        "siUnit": "K",
        "factor": 1.0,
        "accuracy": {
            "model": "combined",
            "systematic": {
                "model": "percent_reading_plus_absolute",
                "relativePctReading": 1.0,
                "absoluteOffset": 0.15,
            },
            "random": {
                "model": "random_sigma",
                "randomSigma": 0.2,
            },
            "confidenceK": 2.0,
        },
    },
    ui_mode="generic",
    ui_default_template="tpl_metric",
    ui_views=[
        {
            "id": "metric",
            "label": "Metric",
            "icon": "Maximize2",
            "template": "tpl_metric",
        }
    ],
)
builder.add_task(
    task_id=f"{SENSOR_ID}_sinus_task",
    name="Sinus Generator",
    task_type="GENERATOR",
    group_id="plugin_sine_gen_v1",
    # Not virtual: this client is the data source. A virtual task would make the
    # workbench start its own JS sine factory on the same sourceId in parallel.
    virtual=False,
    color="#3b82f6",
    tags=["Sine", "Test"],
    config={
        "frequency": 10,
        "amplitude": 5.0,
        "dcOffset": 0.0,
        "phaseOffset": 0,
        "noiseEnabled": True,
        "range": [-10, 10],
        "unit": "V",
        "factor": 1.0,
        "accuracy": {
            "model": "combined",
            "systematic": {
                "model": "absolute",
                "absoluteOffset": 0.02,
            },
            "random": {
                "model": "random_sigma",
                "randomSigma": 0.03,
            },
            "confidenceK": 2.0,
        },
    },
    ui_mode="generic",
    ui_default_template="system_sine_gen",
    ui_views=[
        {
            "id": "control",
            "label": "Control",
            "icon": "Settings",
            "template": "system_sine_gen",
        },
        {
            "id": "metric",
            "label": "Metric",
            "icon": "Maximize2",
            "template": "tpl_metric",
        },
    ],
)
DEVICE_MANIFEST = builder.build()

OVERRIDES_FILE = os.path.join(
    project_root, "elab_clients", "temp_test_client_overrides.json"
)
load_overrides(DEVICE_MANIFEST, OVERRIDES_FILE)


# ==========================================
# 1. DISCOVERY LOGIC
# ==========================================
def discover_server(max_attempts=5):
    """Finds the dispatcher with short timeouts and retry logic."""
    return discover_dispatcher(
        UDP_PORT, logger, max_attempts=max_attempts, timeout_sec=2.0
    )


# ==========================================
# 2. DATA LOGIC
# ==========================================
def validate_payload(payload):
    """Prevents empty or malformed payloads from being sent."""
    if not payload.get("sourceId"):
        return False
    if payload.get("value") is None and payload.get("values") is None:
        return False
    return True


class SinusTask:
    """Generates and sends sine-wave data in configurable chunks."""

    def __init__(self, task_id, initial_config, send_callback, is_connected_event):
        self.task_id = task_id
        self.config = initial_config
        self.send_callback = send_callback
        self.is_connected_event = is_connected_event
        self.phase = 0
        self.sample_rate = 2000
        self.chunk_size = 1024

    def update_config(self, new_config):
        """Updates the task configuration and emits a matching update event."""
        logger.debug("Updating sine task configuration: %s", new_config)
        self.config.update(new_config)
        # Mirror the updated configuration back to the UI to keep widgets in sync.
        if sio is not None:
            sio.emit(
                "provider_meta_changed",
                {"task_id": self.task_id, "changes": {"config": self.config}},
            )

    def run(self):
        """Generates and sends sine data in chunks."""
        logger.info("🚀 Starting sine generator task...")
        while True:
            if self.is_connected_event.is_set():
                loop_start_time = time.time()

                freq = self.config.get("frequency", 10)
                amp = self.config.get("amplitude", 5.0)
                dc_offset = float(self.config.get("dcOffset", 0.0) or 0.0)
                phase_offset = math.radians(
                    float(self.config.get("phaseOffset", 0) or 0)
                )
                noise_enabled = self.config.get("noiseEnabled", True)

                values = []
                timestamps = []

                phase_increment = 2 * math.pi * freq / self.sample_rate

                for i in range(self.chunk_size):
                    value = amp * math.sin(self.phase + phase_offset) + dc_offset
                    if noise_enabled:
                        value += (random.random() - 0.5) * 0.1

                    values.append(value)
                    timestamps.append((loop_start_time + i / self.sample_rate) * 1000)
                    self.phase += phase_increment

                if self.phase > 2 * math.pi:
                    self.phase -= 2 * math.pi

                payload = {
                    "sourceId": self.task_id,
                    "values": values,
                    "timestamps": timestamps,
                    "distribution": "discrete",
                    "value": values[-1],
                }

                if validate_payload(payload):
                    self.send_callback(payload)

                chunk_duration = self.chunk_size / self.sample_rate
                elapsed = time.time() - loop_start_time
                time.sleep(max(0, chunk_duration - elapsed))
            else:
                time.sleep(1)


def simulate_temp_loop(send_callback, is_connected_event):
    """Generates temperature data and sends it to the server."""
    logger.info("🚀 Starting temperature simulation (2 Hz)...")
    phase = 0
    try:
        while True:
            if is_connected_event.is_set():
                timestamp = time.time()
                phase += 0.1
                value = 22.0 + (5.0 * math.sin(phase)) + random.gauss(0, 0.2)

                payload = {
                    "sourceId": f"{SENSOR_ID}_task",
                    "value": value,
                    "timestamp": timestamp * 1000,
                    "unit": "°C",
                }

                if validate_payload(payload):
                    send_callback(payload)

                time.sleep(0.5)
            else:
                time.sleep(1)
    except KeyboardInterrupt:
        logger.info("🛑 Stopping temperature simulation...")


# ==========================================
# MAIN ROUTING & SOCKET.IO
# ==========================================
if __name__ == "__main__":
    server_url = discover_server()
    if not server_url:
        sys.exit(1)

    sio = socketio.Client()
    connected_event = threading.Event()
    auth = ProviderAuth(device_id=SENSOR_ID)
    auth.bind(sio)

    def _emit_data(payload):
        """Sign and emit a data_stream packet (no-op if not yet approved)."""
        if not auth.has_secret():
            return
        sio.emit("data_stream", auth.sign(payload))

    def shutdown_handler(_signum, _frame):
        """Saves overrides and shuts the client down cleanly."""
        logger.info("\ud83d\uded1 Client shutting down, saving overrides...")
        save_overrides(DEVICE_MANIFEST, OVERRIDES_FILE)
        if sio.connected:
            sio.disconnect()
        sys.exit(0)

    # Register signal handlers for graceful shutdown.
    signal.signal(signal.SIGINT, shutdown_handler)
    signal.signal(signal.SIGTERM, shutdown_handler)

    sinus_task_manifest = next(
        (
            task
            for task in DEVICE_MANIFEST["tasks"]
            if task["id"] == f"{SENSOR_ID}_sinus_task"
        ),
        None,
    )
    if not sinus_task_manifest:
        logger.error("Sine task not found in manifest!")
        sys.exit(1)

    sinus_task_instance = SinusTask(
        task_id=sinus_task_manifest["id"],
        initial_config=sinus_task_manifest["config"],
        send_callback=_emit_data,
        is_connected_event=connected_event,
    )

    @sio.event
    def connect():  # pylint: disable=missing-function-docstring
        connected_event.set()
        logger.info("✅ Connected to dispatcher!")
        auth.send_register(sio, DEVICE_MANIFEST)

    @sio.event
    def disconnect():  # pylint: disable=missing-function-docstring
        connected_event.clear()
        logger.warning("⚠️ Connection interrupted.")

    @sio.event
    def execute_command(data):  # pylint: disable=missing-function-docstring
        command = data.get("command", {})
        target_id = data.get("provider_id", "").replace("prov_", "")

        if (
            target_id == sinus_task_instance.task_id
            and command.get("action") == "update_config"
        ):
            sinus_task_instance.update_config(command.get("payload", {}))

        elif command.get("action") == "update_meta":
            payload = command.get("payload", {})
            logger.debug("🎨 UI changed metadata: %s for %s", payload, target_id)
            if apply_task_meta_update(DEVICE_MANIFEST, target_id, payload):
                # Echo metadata updates back to the UI.
                sio.emit(
                    "provider_meta_changed", {"task_id": target_id, "changes": payload}
                )
                save_overrides(DEVICE_MANIFEST, OVERRIDES_FILE)

    try:
        sio.connect(server_url)

        temp_thread = threading.Thread(
            target=simulate_temp_loop,
            args=(_emit_data, connected_event),
            daemon=True,
        )
        sinus_thread = threading.Thread(target=sinus_task_instance.run, daemon=True)

        temp_thread.start()
        sinus_thread.start()

        while True:
            time.sleep(1)

    except socketio.exceptions.ConnectionError as e:  # type: ignore[attr-defined] # pylint: disable=no-member
        logger.error("❌ Could not connect: %s", e)
        sys.exit(1)

    # Keep the main thread alive
    while True:
        time.sleep(1)
