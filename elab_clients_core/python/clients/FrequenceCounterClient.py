# pylint: disable=invalid-name
"""
E-Lab client that simulates a frequency counter and temperature sensor.

This client can run in two modes:
1. Dispatcher mode: connects to a central dispatcher server.
2. Standalone mode: runs as an independent server with its own web UI.
"""
import time
import json
import socket
import random
import logging
import math
import os
import sys
import platform
import threading
import urllib.request
import urllib.error
import argparse
from typing import Optional

import psutil
import socketio
from flask import Flask, Response
from flask_cors import CORS
from flask_socketio import SocketIO


# Add parent directory to path for imports to allow finding 'elab_server' or 'shared'
project_root = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)
sys.path.insert(0, project_root)
core_clients_dir = os.path.join(project_root, "elab_clients_core")
python_clients_root = os.path.join(core_clients_dir, "python")

# Add the client directory as an import root for the shared-module fallback.
clients_dir = os.path.dirname(os.path.abspath(__file__))
if clients_dir not in sys.path:
    sys.path.insert(0, clients_dir)


# --- GLOBALS ---
IS_RASPBERRY_ENV = False
DEVICE_MANIFEST = None  # Built dynamically at startup.

# --- CONFIGURATION ---
DISPATCHER_PORT = 5000
UDP_DISCOVERY_PORT = 5005

INSTANCE_ID = int(time.time() * 1000) % 100000
DEVICE_ID = f"smart_counter_{INSTANCE_ID}"

DISCOVERY_ATTEMPTS = 3
SAMPLE_RATE = 10
CHUNK_SIZE = 5
CHUNK_DURATION = CHUNK_SIZE / SAMPLE_RATE

PLUGIN_FILENAME = "freq_counter_plugin.js"
INDEX_FILENAME = "index.html"
# ASSETS_DIR will be defined after environment detection

# --- LOGGING ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(name)s: %(message)s')
logger = logging.getLogger("Frequence Counter")


def _extract_component_name(assets_dir: str, plugin_filename: str) -> str:
    """Extracts the component name from the JS plugin file (SSOT).

    Parses the first ``registerElabPlugin('Name', ...)`` call.
    """
    plugin_path = os.path.join(assets_dir, plugin_filename)
    try:
        with open(plugin_path, 'r', encoding='utf-8') as f:
            for line in f:
                if 'registerElabPlugin' in line:
                    start = line.index("'") + 1
                    end = line.index("'", start)
                    return line[start:end]
    except (FileNotFoundError, ValueError):
        pass
    return "UnknownPlugin"

# pylint: disable=C0301

# --- DYNAMIC IMPORTS & ENV DETECTION ---
try:
    # Standard location for dev environment
    from elab_server.manifest_builder import ManifestBuilder
    logger.debug("Loaded ManifestBuilder from 'elab_server'.")
except ImportError:
    # Fallback for alternative structure (e.g., on Raspberry Pi)
    pi_path = os.path.join(project_root, 'shared')
    sys.path.insert(0, pi_path)
    try:
        from manifest_builder import ManifestBuilder  # type: ignore[import-not-found]
        logger.debug("Loaded ManifestBuilder from 'shared' directory.")
        IS_RASPBERRY_ENV = True
    except ImportError:
        logger.critical("CRITICAL: Could not find 'manifest_builder.py'. Searched in 'elab_server' and 'shared'.")
        sys.exit(1)

# Define ASSETS_DIR based on environment
if IS_RASPBERRY_ENV:
    # On Pi, assets are in the shared folder, one level up from 'scripts'
    ASSETS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'shared'))
else:
    # Dev environment keeps assets in the canonical python/assets folder.
    ASSETS_DIR = os.path.join(python_clients_root, "assets")
logger.info("Asset directory set to: %s", ASSETS_DIR)

# SSOT: Component name is defined once in the JS plugin file
COMPONENT_NAME = _extract_component_name(ASSETS_DIR, PLUGIN_FILENAME)
logger.info("Plugin component name: %s", COMPONENT_NAME)

try:
    from shared.discovery import discover_dispatcher  # type: ignore[import-not-found]
    from shared.overrides import load_overrides, save_overrides, apply_task_meta_update  # type: ignore[import-not-found]
    from shared.plugin_security import compute_plugin_sri  # type: ignore[import-not-found]
except ImportError:
    from elab_clients_core.python.shared.discovery import discover_dispatcher  # type: ignore[import-not-found]
    from elab_clients_core.python.shared.overrides import load_overrides, save_overrides, apply_task_meta_update  # type: ignore[import-not-found]
    try:
        from elab_clients_core.python.shared.plugin_security import compute_plugin_sri  # type: ignore
    except ImportError:
        compute_plugin_sri = None  # type: ignore[assignment]

OVERRIDES_FILE = os.path.join(core_clients_dir, 'freq_counter_overrides.json')


def get_free_port(start_port=8080, max_attempts=10):
    """Finds a free port starting at start_port."""
    for port in range(start_port, start_port + max_attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(('0.0.0.0', port)) != 0:
                return port
    return start_port  # Fallback

# --- HELPER: RESOLVE LOCAL IP ---
def get_local_ip(target_host=None):
    """Determines the device's local IP address.

    If target_host is provided, it resolves the IP used to reach that host.
    This is useful in dispatcher mode.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect((target_host or '8.8.8.8', 80))
        ip_address = s.getsockname()[0]
    except socket.error:
        ip_address = 'localhost'
    finally:
        s.close()
    return ip_address

LOCAL_IP_ADDRESS = get_local_ip()
MY_WEB_PORT = get_free_port()
PLUGIN_URL = f"http://{LOCAL_IP_ADDRESS}:{MY_WEB_PORT}/{PLUGIN_FILENAME}"

PLUGIN_INTEGRITY: Optional[str] = None
if compute_plugin_sri is not None:
    try:
        PLUGIN_INTEGRITY = compute_plugin_sri(os.path.join(ASSETS_DIR, PLUGIN_FILENAME))
        logger.info("🔒 Plugin SRI hash: %s", PLUGIN_INTEGRITY)
    except (FileNotFoundError, OSError) as exc:
        logger.warning("Could not compute plugin SRI: %s", exc)

# --- HELPER: READ CPU TEMPERATURE ---
def get_cpu_temperature():
    """
    Reads the CPU temperature.

    Tries multiple methods and falls back to simulation if no real
    hardware sensor is available.
    """
    # Method 1: Sysfs, the fastest direct path on Linux/Raspberry Pi.
    try:
        with open("/sys/class/thermal/thermal_zone0/temp", "r", encoding="utf-8") as f:
            temp_mc = int(f.read().strip())
            return temp_mc / 1000.0
    except (IOError, FileNotFoundError):
        pass

    # Method 2: WMI on Windows.
    if platform.system() == "Windows":
        try:
            import wmi  # type: ignore[import-not-found]
            w = wmi.WMI(namespace="root\\wmi")
            temperature_info = w.MSAcpi_ThermalZoneTemperature()
            if temperature_info:
                raw_temp = temperature_info[0].CurrentTemperature
                return (raw_temp / 10.0) - 273.15
        except (ImportError, OSError):  # pylint: disable=broad-exception-caught
            pass

    # Method 3: cross-platform psutil fallback.
    try:
        if hasattr(psutil, 'sensors_temperatures'):
            temps = psutil.sensors_temperatures()  # type: ignore[attr-defined]
            if temps:
                if 'coretemp' in temps and temps['coretemp']:
                    return temps['coretemp'][0].current
                # Fall back to the first available sensor that reports values.
                for sensor_values in temps.values():
                    if sensor_values:
                        return sensor_values[0].current
    except (AttributeError, OSError):
        pass

    # Method 4: simulation fallback, mainly for Windows.
    if platform.system() == "Windows":
        # Simulate a plausible temperature with small fluctuations.
        base_temp = 45
        temp_variation = 15 * math.sin(time.time() * 0.1)
        return round(base_temp + temp_variation + random.uniform(-0.5, 0.5), 2)

    return None  # All methods failed.

# Detect whether a real sensor was found.
INITIAL_TEMP = get_cpu_temperature()
IS_SIMULATED = False
if INITIAL_TEMP is not None:
    # Check whether the reading is simulated. This only happens on Windows
    # when all real sensor lookups fail.
    if platform.system() == "Windows":
        # Bypass higher-level fallbacks and check whether a real sysfs source exists.
        try:
            with open("/sys/class/thermal/thermal_zone0/temp", "r", encoding="utf-8"):
                pass
            # If this works, the reading is not simulated.
        except FileNotFoundError:
            IS_SIMULATED = True  # Windows environment without a real sensor.

    if IS_SIMULATED:
        logger.warning("ℹ️ Kein echter Temperatursensor auf Windows gefunden. "
                    "CPU-Temperatur wird simuliert.")
    else:
        logger.info("🌡️ Echter Temperatursensor erkannt! Initiale Temperatur: %s °C", INITIAL_TEMP)
else:
    logger.warning("ℹ️ Kein Temperatursensor gefunden. Temperatur wird nicht angezeigt.")

def download_schema(dispatcher_url):
    """Downloads the manifest schema from the dispatcher server."""
    schema_url = f"{dispatcher_url.replace('http:', 'http:')}/schemas/ManifestSchema.json"
    logger.info("⬇️ Downloading schema from %s", schema_url)
    try:
        with urllib.request.urlopen(schema_url, timeout=5) as response:
            if response.status == 200:
                logger.info("✅ Schema downloaded successfully.")
                return json.loads(response.read().decode('utf-8'))
            logger.error("❌ Failed to download schema, server returned status %s", response.status)
            return None
    except (urllib.error.URLError, socket.timeout) as e:
        logger.error("❌ Error while downloading schema: %s", e)
        return None

def build_manifest(schema_dict=None):
    """Builds the device manifest using an optional external schema."""
    global DEVICE_MANIFEST  # pylint: disable=global-statement
    logger.info("🛠️ Building device manifest...")
    builder = ManifestBuilder(DEVICE_ID, "Smart Freq & Temp Counter",
                              schema_dict=schema_dict)
    builder.add_task(
        task_id=f"{DEVICE_ID}_t1",
        name="Channel A (Freq)",
        task_type="SENSOR",
        group_id="freq_plugin_v1",
        virtual=False,
        color="#d946ef",
        config={
            "range": [44000, 44200],
            "unit": "Hz",
            "factor": 1.0,
            "accuracy": {
                "model": "combined",
                "systematic": {
                    "model": "percent_reading_plus_absolute",
                    "relativePctReading": 0.01,
                    "absoluteOffset": 1.0,
                },
                "random": {
                    "model": "random_sigma",
                    "randomSigma": 2.0,
                },
                "confidenceK": 2.0,
            },
        },
        ui_mode="custom",
        ui_url=PLUGIN_URL,
        ui_integrity=PLUGIN_INTEGRITY,
        ui_component_name=COMPONENT_NAME
    )
    builder.add_task(
        task_id=f"{DEVICE_ID}_t2",
        name="Channel B (CPU Temp)",
        task_type="SENSOR",
        group_id="freq_plugin_v1",
        virtual=False,
        color="#ef4444",
        config={
            "range": [20, 85],
            "unit": "°C",
            "factor": 1.0,
            "accuracy": {
                "model": "combined",
                "systematic": {
                    "model": "percent_reading_plus_absolute",
                    "relativePctReading": 0.5,
                    "absoluteOffset": 0.3,
                },
                "random": {
                    "model": "random_sigma",
                    "randomSigma": 0.2,
                },
                "confidenceK": 2.0,
            },
        },
        ui_mode="custom",
        ui_url=PLUGIN_URL,
        ui_integrity=PLUGIN_INTEGRITY,
        ui_component_name=COMPONENT_NAME
    )
    try:
        DEVICE_MANIFEST = builder.build()
        logger.info("\u2705 Manifest built and validated successfully.")
        load_overrides(DEVICE_MANIFEST, OVERRIDES_FILE)
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error("💥 Failed to build manifest: %s", e)
        DEVICE_MANIFEST = None


# ==========================================
# 1. SHARED DATA LOGIC
# ==========================================


def validate_payload(payload):
    """Performs a lightweight O(1) validation to reject broken payloads."""
    if not payload.get("sourceId") or payload.get("values") is None:
        logger.error("⚠️ Skipping invalid payload: Missing 'sourceId' or 'values'")
        return False
    return True

def measurement_loop(send_callback):
    """Generates data and forwards it through a transport-agnostic callback."""
    logger.info("🚀 Starting Measurement Loop (%s Hz)...", SAMPLE_RATE)
    phase = 0.0
    loop_count = 0

    while True:
        loop_start = time.time()
        try:
            now_ts = loop_start
            start_ts = now_ts - CHUNK_DURATION

            # Simulated frequency data.
            freq_values = []
            for n in range(CHUNK_SIZE):
                t = start_ts + (n / SAMPLE_RATE)
                phase += 0.1
                base_freq = 44100
                drift = 50 * math.sin(t * 0.5)
                noise = random.randint(-5, 5)
                freq_values.append(int(base_freq + drift + noise))

            payload_freq = {
                "sourceId": f"{DEVICE_ID}_t1",
                "values": freq_values,
                "distribution": "linear",
                "startTime": start_ts * 1000,
                "endTime": now_ts * 1000,
                "timestamp": now_ts * 1000,
                "value": freq_values[-1]
            }

            if validate_payload(payload_freq):
                send_callback(payload_freq)

            # CPU temperature data in real time, when available.
            cpu_temp = get_cpu_temperature()
            if cpu_temp is not None:
                temp_values = [cpu_temp] * CHUNK_SIZE
                payload_temp = {
                    "sourceId": f"{DEVICE_ID}_t2",
                    "values": temp_values,
                    "distribution": "linear",
                    "startTime": start_ts * 1000,
                    "endTime": now_ts * 1000,
                    "timestamp": now_ts * 1000,
                    "value": cpu_temp
                }
                if validate_payload(payload_temp):
                    send_callback(payload_temp)

        except (ValueError, TypeError, OSError) as e:
            logger.error("💥 Unhandled exception in measurement_loop: %s", e, exc_info=True)
            # Briefly pause to avoid a tight error loop.
            time.sleep(CHUNK_DURATION)
            continue  # Try the next iteration.

        # Keep the loop cadence stable.
        finally:
            elapsed = time.time() - loop_start
            sleep_time = max(0, CHUNK_DURATION - elapsed)
            time.sleep(sleep_time)
            loop_count += 1


# ==========================================
# 2. DISCOVERY LOGIC
# ==========================================
def discover_dispatcher_udp():
    """Finds the dispatcher via UDP broadcast."""
    return discover_dispatcher(
        UDP_DISCOVERY_PORT,
        logger,
        max_attempts=1,
        timeout_sec=3.0,
        prefer_non_loopback=True,
    )


# ==========================================
# 3. MODE A: LIGHTWEIGHT CLIENT (Dispatcher)
# ==========================================
def run_dispatcher_mode(dispatcher_url):
    """Starts the client in dispatcher mode."""
    logger.info("🔗 Starting in DISPATCHER MODE. Connecting to %s", dispatcher_url)

    # --- Thread-Safe Connection State ---
    upstream_connected = threading.Event()

    # Start the mini web server used by the workbench to load the remote plugin.
    app = Flask(__name__)
    CORS(app)

    # Read as raw bytes so the hash computed by compute_plugin_sri (binary)
    # matches the bytes the browser receives. Reading as text on Windows
    # silently converts CRLF -> LF and breaks the SRI check.
    try:
        with open(os.path.join(ASSETS_DIR, PLUGIN_FILENAME), 'rb') as f:
            plugin_js = f.read()
    except FileNotFoundError:
        plugin_js = b"console.error('Plugin File not found');"

    @app.route(f'/{PLUGIN_FILENAME}')
    def serve_plugin():
        return Response(plugin_js, mimetype='application/javascript')

    threading.Thread(
        target=lambda: app.run(host='0.0.0.0', port=MY_WEB_PORT, debug=False, use_reloader=False),
        daemon=True
    ).start()

    # Connect to the upstream Socket.IO dispatcher.
    sio = socketio.Client()

    @sio.event
    def connect():
        upstream_connected.set()
        logger.info("✅ Connected to Upstream Dispatcher!")
        sio.emit('register_provider', DEVICE_MANIFEST)

    @sio.event
    def disconnect():
        upstream_connected.clear()
        logger.warning("⚠️ Disconnected from Upstream Dispatcher")

    # Listen for global config and metadata updates coming from the UI.
    @sio.event
    def execute_command(data):
        command = data.get('command', {})
        if command.get('action') == 'update_meta':
            payload = command.get('payload', {})
            logger.debug("🎨 UI requested meta update: %s", payload)

            # Update the in-memory manifest so reconnects expose the latest UI state.
            if DEVICE_MANIFEST is None:
                return
            target_id = data.get('provider_id', '').replace('prov_', '')
            if apply_task_meta_update(DEVICE_MANIFEST, target_id, payload):
                save_overrides(DEVICE_MANIFEST, OVERRIDES_FILE)

    # Only emit data while the upstream connection is available.
    def safe_send(payload):
        if upstream_connected.is_set():
            sio.emit('data_stream', payload)

    try:
        sio.connect(dispatcher_url)
        # Pass the thread-safe callback into the measurement loop.
        measurement_loop(safe_send)
    except socketio.exceptions.ConnectionError as e:  # type: ignore[attr-defined] # pylint: disable=no-member
        logger.error("❌ Connection lost or failed: %s", e)


# ==========================================
# 4. MODE B: STANDALONE HOST
# ==========================================
def run_standalone_mode():
    """Starts the client in standalone mode with a local UI."""
    logger.info("🏠 Starting in STANDALONE MODE (Local Webserver)")

    app = Flask(__name__)
    CORS(app)
    local_server = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

    # See note in dispatcher mode: serve raw bytes so SRI matches.
    try:
        with open(os.path.join(ASSETS_DIR, PLUGIN_FILENAME), 'rb') as f:
            plugin_js = f.read()
    except FileNotFoundError:
        plugin_js = b"console.error('Plugin File not found');"

    @app.route('/')
    def serve_index():
        try:
            with open(os.path.join(ASSETS_DIR, INDEX_FILENAME), 'r', encoding='utf-8') as f:
                return f.read()
        except FileNotFoundError:
            return "index.html missing in assets/"

    @app.route(f'/{PLUGIN_FILENAME}')
    def serve_plugin():
        return Response(plugin_js, mimetype='application/javascript')

    @local_server.on('connect')
    def handle_local_connect():
        logger.info("💻 Local Browser connected!")
        local_server.emit('available_providers', {'providers': [DEVICE_MANIFEST]})

    local_server.start_background_task(
        measurement_loop,
        lambda payload: local_server.emit('data_stream', payload)
    )

    logger.info("🌐 Web UI running at http://%s:%s", LOCAL_IP_ADDRESS, MY_WEB_PORT)
    local_server.run(app, host='0.0.0.0', port=MY_WEB_PORT, debug=False, allow_unsafe_werkzeug=True)


# ==========================================
# MAIN ROUTING
# ==========================================
if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='E-Lab Frequency Counter Client')
    parser.add_argument('--server-ip', type=str, help='Manually specify the server IP to bypass UDP discovery.')
    args = parser.parse_args()

    DISPATCHER_URL = None
    schema = None

    if args.server_ip:
        logger.info("🔩 Manual server IP provided: %s", args.server_ip)
        DISPATCHER_URL = f"http://{args.server_ip}:{DISPATCHER_PORT}"
        schema = download_schema(DISPATCHER_URL)
    else:
        logger.info("🌐 Automatic discovery mode.")
        for i in range(DISCOVERY_ATTEMPTS):
            logger.info("🔄 Connection Attempt %d/%d...", i + 1, DISCOVERY_ATTEMPTS)
            DISPATCHER_URL = discover_dispatcher_udp()
            if DISPATCHER_URL:
                schema = download_schema(DISPATCHER_URL)
                break

    if DISPATCHER_URL:
        # Re-derive local IP using the dispatcher host so the plugin URL
        # is reachable from the same network as the e_Lab server.
        try:
            from urllib.parse import urlparse
            dispatcher_host = urlparse(DISPATCHER_URL).hostname
            if dispatcher_host:
                LOCAL_IP_ADDRESS = get_local_ip(dispatcher_host)
                PLUGIN_URL = f"http://{LOCAL_IP_ADDRESS}:{MY_WEB_PORT}/{PLUGIN_FILENAME}"
                logger.info("🌐 Plugin URL updated to: %s", PLUGIN_URL)
        except (OSError, ValueError) as e:
            logger.warning("Could not update plugin URL from dispatcher: %s", e)

        build_manifest(schema_dict=schema)
        if DEVICE_MANIFEST:
            run_dispatcher_mode(DISPATCHER_URL)
        else:
            logger.error("❌ Exiting: Manifest could not be built.")
    else:
        logger.warning("⚠️ No Dispatcher found. Building manifest with local schema fallback.")
        build_manifest()  # Falls back to the local schema when no dispatcher is found.
        if DEVICE_MANIFEST:
            run_standalone_mode()
        else:
            logger.error("❌ Exiting: Manifest could not be built even with fallback.")
