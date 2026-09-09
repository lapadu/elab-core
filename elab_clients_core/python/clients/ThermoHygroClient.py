# pylint: disable=invalid-name
"""
E-Lab Client for Govee Bluetooth LE Thermometer & Hygrometer Sensors.

This client implements the E-Lab Provider interface offering two distinct tasks:
1. Temperature measurement (configurable between °C and °F)
2. Humidity measurement (%)

Features:
- Unique GUID provider identification persisted across restarts.
- Live continuous scanning for BLE sensors in the workbench configuration view.
- Persistent configuration storage for target device mac address across restarts.
- Optional simulation mode (-s / --simulate) for development and testing without physical hardware.
"""

import sys
import time
import json
import logging
import os
import random
import asyncio
import threading
import argparse
from datetime import datetime
from typing import Optional, Dict, Any, List

import socketio

# Ensure UTF-8 console output for symbols and emojis on Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
elif sys.stdout and not getattr(sys.stdout, "closed", True):
    import codecs

    sys.stdout = codecs.getwriter("utf-8")(sys.stdout.buffer, "replace")

# Add project root to import path
project_root = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

core_clients_dir = os.path.join(project_root, "elab_clients_core")
python_clients_root = os.path.join(core_clients_dir, "python")
if python_clients_root not in sys.path:
    sys.path.insert(0, python_clients_root)

try:
    from elab_server.manifest_builder import ManifestBuilder
except ImportError:
    shared_root = os.path.join(project_root, "shared")
    sys.path.insert(0, shared_root)
    from manifest_builder import ManifestBuilder  # type: ignore[import-not-found]

try:
    from elab_clients_core.python.shared.discovery import discover_dispatcher  # type: ignore[import-not-found]
    from elab_clients_core.python.shared.identity import (  # type: ignore[import-not-found]
        resolve_device_identity,
    )
    from elab_clients_core.python.shared.overrides import (  # type: ignore[import-not-found]
        load_overrides,
        save_overrides,
    )
    from elab_clients_core.python.shared.auth import ProviderAuth  # type: ignore[import-not-found]
except ImportError:
    from shared.discovery import discover_dispatcher  # type: ignore[import-not-found]
    from shared.identity import resolve_device_identity  # type: ignore[import-not-found]
    from shared.overrides import (  # type: ignore[import-not-found]
        load_overrides,
        save_overrides,
    )
    from shared.auth import ProviderAuth  # type: ignore[import-not-found]

# Attempt to import Bleak for Bluetooth LE scanning
try:
    import bleak
    from bleak import BleakScanner

    HAS_BLEAK = True
except ImportError:
    HAS_BLEAK = False
    bleak = None
    BleakScanner = None

# --- LOGGING SETUP ---
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("ThermoHygroClient")

# --- GUID & CONSTANTS ---
GUID_FILE = os.path.join(core_clients_dir, "thermo_hygro_guid.txt")


def _migrate_legacy_guid() -> None:
    """Remove the pre-2.1 GUID file that was shared by every checkout.

    It lived inside the repository, so all instances derived the same id and
    the dispatcher could not tell two sensors apart.
    """
    if os.path.exists(GUID_FILE):
        try:
            os.remove(GUID_FILE)
            logger.info(
                "Removed legacy GUID file %s; identity now lives in ~/.elab/identity.",
                GUID_FILE,
            )
        except OSError as exc:
            logger.warning("Could not remove legacy GUID file: %s", exc)


GOVEE_COMPANY_ID = 0xEC88
UDP_DISCOVERY_PORT = 5005
DEVICE_MODEL = "govee_thermo_hygro"

_migrate_legacy_guid()


def _resolve_identity(bound_address: Optional[str]) -> Any:
    """Resolve this wrapper's identity, preferring the bound sensor's BLE MAC.

    An unbound wrapper has no hardware to point at, so it runs on a locally
    persisted id. Once an operator picks a sensor its MAC becomes the anchor:
    the identity then follows the thermometer rather than the host, which is
    what keeps several sensors apart in a shared measurement.
    """
    if bound_address:
        return resolve_device_identity(
            DEVICE_MODEL,
            anchor_value=str(bound_address),
            anchor="ble_mac",
            name="Govee Thermo & Hygro Sensor",
        )
    return resolve_device_identity(DEVICE_MODEL, name="Govee Thermo & Hygro Sensor")


IDENTITY = _resolve_identity(None)
DEVICE_ID = IDENTITY.device_id
PROVIDER_ID = DEVICE_ID
TEMP_TASK_ID = IDENTITY.task_id("temp")
HUMIDITY_TASK_ID = IDENTITY.task_id("humidity")
OVERRIDES_FILE = os.path.join(core_clients_dir, "thermo_hygro_overrides.json")

# Global operating state
sio = socketio.Client(reconnection=True, reconnection_attempts=10, reconnection_delay=2)
auth = ProviderAuth(DEVICE_ID)
is_scanning: bool = False
target_address: Optional[str] = None
target_name: Optional[str] = None
current_unit: str = "°C"
is_simulated: bool = False

# Map mac_address -> device dictionary
discovered_devices: Dict[str, Dict[str, Any]] = {}
latest_readings: Dict[str, Dict[str, Any]] = {}

# Dynamic manifest
DEVICE_MANIFEST: Optional[Dict[str, Any]] = None


def create_manifest() -> Dict[str, Any]:
    """Creates the provider manifest with Temperature and Humidity tasks and generic views."""
    builder = ManifestBuilder(
        provider_id=PROVIDER_ID,
        name="Govee Thermo & Hygro Sensor",
        category="HARDWARE",
        persist_config=True,
        device_id=IDENTITY.device_id,
        model=IDENTITY.model,
        device_anchor=IDENTITY.anchor,
        device_name=IDENTITY.name,
    )

    # Task 1: Temperature Sensor (°C / °F) - Rose Color
    builder.add_task(
        task_id=TEMP_TASK_ID,
        name="Temperature",
        task_type="SENSOR",
        color="#f43f5e",
        tags=["Temperature", "Climate", "BLE", "Sensor"],
        config={
            "unit": "°C",
            "supportedUnits": ["°C", "°F"],
            "targetAddress": None,
            "targetName": "No Sensor Selected",
            "isScanning": False,
            "discoveredDevices": [],
            "range": [-20.0, 50.0],
            "min": -20.0,
            "max": 50.0,
            "factor": 1.0,
            "dataType": "float",
        },
        ui_mode="generic",
        ui_default_template="tpl_metric_trend",
        ui_views=[
            {
                "id": "trend",
                "label": "Trend",
                "icon": "TrendingUp",
                "template": "tpl_metric_trend",
            },
            {
                "id": "config",
                "label": "Scanner",
                "icon": "Radio",
                "template": "tpl_device_scanner_config",
            },
        ],
    )

    # Task 2: Humidity Sensor (%) - Cyan Color
    builder.add_task(
        task_id=HUMIDITY_TASK_ID,
        name="Humidity",
        task_type="SENSOR",
        color="#06b6d4",
        tags=["Humidity", "Climate", "BLE", "Sensor"],
        config={
            "unit": "%",
            "supportedUnits": ["%"],
            "targetAddress": None,
            "targetName": "No Sensor Selected",
            "isScanning": False,
            "discoveredDevices": [],
            "range": [0.0, 100.0],
            "min": 0.0,
            "max": 100.0,
            "factor": 1.0,
            "dataType": "float",
        },
        ui_mode="generic",
        ui_default_template="tpl_metric_trend",
        ui_views=[
            {
                "id": "trend",
                "label": "Trend",
                "icon": "TrendingUp",
                "template": "tpl_metric_trend",
            },
            {
                "id": "config",
                "label": "Scanner",
                "icon": "Radio",
                "template": "tpl_device_scanner_config",
            },
        ],
    )

    return builder.build()


def sync_manifest_from_state() -> None:
    """Updates both tasks in DEVICE_MANIFEST with the current global target_address and scan list."""
    global DEVICE_MANIFEST, target_address, target_name, is_scanning, discovered_devices, current_unit, is_simulated
    if not DEVICE_MANIFEST:
        return

    dev_list = list(discovered_devices.values())
    for task in DEVICE_MANIFEST.get("tasks", []):
        config = task.setdefault("config", {})
        config["targetAddress"] = target_address
        config["targetName"] = target_name or (
            "Kein Sensor gewählt" if not target_address else str(target_address)
        )
        config["isScanning"] = is_scanning
        config["discoveredDevices"] = dev_list
        config["simulated"] = is_simulated
        if task["id"] == TEMP_TASK_ID:
            config["unit"] = current_unit


def emit_meta_changed() -> None:
    """Emits provider_meta_changed for both temperature and humidity tasks."""
    if not sio.connected or not DEVICE_MANIFEST:
        return

    dev_list = list(discovered_devices.values())
    for task in DEVICE_MANIFEST.get("tasks", []):
        t_id = task["id"]
        cfg_update: Dict[str, Any] = {
            "targetAddress": target_address,
            "targetName": target_name
            or ("Kein Sensor gewählt" if not target_address else str(target_address)),
            "isScanning": is_scanning,
            "discoveredDevices": dev_list,
        }
        if t_id == TEMP_TASK_ID:
            cfg_update["unit"] = current_unit

        try:
            sio.emit(
                "provider_meta_changed",
                {"task_id": t_id, "changes": {"config": cfg_update}},
            )
        except Exception as err:
            logger.debug("Failed emitting provider_meta_changed for %s: %s", t_id, err)


def process_measurement(
    address: str, name: str, rssi: int, temp_c: float, humidity: float, battery: int
) -> None:
    """Processes a newly parsed temperature and humidity reading from BLE or simulation."""
    global target_address, is_scanning, latest_readings, discovered_devices

    now = time.time()
    info = {
        "name": name,
        "address": address,
        "rssi": rssi,
        "temp_c": temp_c,
        "humidity": humidity,
        "battery": battery,
        "timestamp": now,
    }
    latest_readings[address] = info

    # If currently in discovery scanning mode, update discovered list and notify UI
    if is_scanning:
        discovered_devices[address] = info
        sync_manifest_from_state()
        emit_meta_changed()

    # If this device matches the persistent target_address, stream data to E-Lab dispatcher!
    if target_address and address.upper() == str(target_address).upper():
        if sio.connected and auth.has_secret():
            # Task 1: Temperature Stream
            out_temp = temp_c if current_unit == "°C" else (temp_c * 1.8 + 32.0)
            try:
                sio.emit(
                    "data_stream",
                    auth.sign(
                        {
                            "sourceId": TEMP_TASK_ID,
                            "value": round(out_temp, 2),
                            "unit": current_unit,
                            "timestamp": now * 1000,
                        }
                    ),
                )
                # Task 2: Humidity Stream
                sio.emit(
                    "data_stream",
                    auth.sign(
                        {
                            "sourceId": HUMIDITY_TASK_ID,
                            "value": round(humidity, 1),
                            "unit": "%",
                            "timestamp": now * 1000,
                        }
                    ),
                )
            except Exception as exc:
                logger.debug("Error emitting sensor stream data: %s", exc)


def ble_detection_callback(device: Any, advertisement_data: Any) -> None:
    """BLE advertisement callback for Govee format packets."""
    name = advertisement_data.local_name or getattr(device, "name", None) or "Unbekannt"
    rssi = getattr(advertisement_data, "rssi", getattr(device, "rssi", -80))

    is_govee_name = any(
        kw in str(name) for kw in ["H5", "GV", "Govee", "B5", "H6", "H7", "Smart"]
    )
    mfg_data = getattr(advertisement_data, "manufacturer_data", {})

    target_id = None
    if GOVEE_COMPANY_ID in mfg_data:
        target_id = GOVEE_COMPANY_ID
    elif 0x88EC in mfg_data:
        target_id = 0x88EC

    if is_govee_name or target_id is not None:
        if target_id is not None and target_id in mfg_data:
            data = mfg_data[target_id]
            if len(data) >= 5:
                encoded_data = int.from_bytes(data[1:4], byteorder="big")
                is_negative = bool(encoded_data & 0x800000)
                encoded_data = encoded_data & 0x7FFFFF

                temp_c = encoded_data / 10000.0
                if is_negative:
                    temp_c = -temp_c

                humidity = (encoded_data % 1000) / 10.0
                battery = data[4]
                process_measurement(
                    device.address, name, rssi, temp_c, humidity, battery
                )


# --- SOCKET.IO EVENT HANDLERS ---
def rebind_identity(bound_address: Optional[str]) -> None:
    """Re-register under the identity derived from the newly bound sensor.

    The dispatcher rejects a second provider claiming ids it already knows, so
    the previous registration has to be withdrawn before the new one is sent.
    """
    global IDENTITY, DEVICE_ID, PROVIDER_ID, TEMP_TASK_ID, HUMIDITY_TASK_ID
    global DEVICE_MANIFEST, auth

    new_identity = _resolve_identity(bound_address)
    if new_identity.device_id == DEVICE_ID:
        return

    old_provider_id = PROVIDER_ID
    IDENTITY = new_identity
    DEVICE_ID = new_identity.device_id
    PROVIDER_ID = DEVICE_ID
    TEMP_TASK_ID = new_identity.task_id("temp")
    HUMIDITY_TASK_ID = new_identity.task_id("humidity")

    DEVICE_MANIFEST = create_manifest()
    load_overrides(DEVICE_MANIFEST, OVERRIDES_FILE)
    sync_manifest_from_state()

    if not sio.connected:
        return
    try:
        sio.emit("deregister_provider", {"provider_id": old_provider_id})
        auth = ProviderAuth(DEVICE_ID)
        auth.bind(sio)
        auth.send_register(sio, DEVICE_MANIFEST)
        logger.info(
            "🆔 Re-registered as %s (anchor=%s)", DEVICE_ID, new_identity.anchor
        )
    except Exception as exc:  # pylint: disable=broad-except
        logger.error("Failed to re-register under new identity: %s", exc)


@sio.event
def connect():
    """Triggered on dispatcher connection."""
    logger.info("🔌 Connected to E-Lab Dispatcher at %s", sio.connection_url)


@sio.event
def disconnect():
    """Triggered on dispatcher disconnection."""
    logger.warning("⚠️ Disconnected from dispatcher.")


@sio.event
def execute_command(data: Dict[str, Any]) -> None:
    """Handles commands received from the workbench UI (scanning, selecting device, changing unit)."""
    global is_scanning, target_address, target_name, discovered_devices, current_unit, DEVICE_MANIFEST
    if not isinstance(data, dict):
        return

    target_id = str(data.get("provider_id", "")).replace("prov_", "")
    if target_id not in (PROVIDER_ID, TEMP_TASK_ID, HUMIDITY_TASK_ID, DEVICE_ID):
        return

    command = data.get("command", {})
    action = command.get("action")
    payload = command.get("payload", {})

    logger.info("📥 Received command action='%s', payload=%r", action, payload)

    if action == "start_scan":
        is_scanning = True
        discovered_devices.clear()
        logger.info("🔍 Device scanning started via UI command.")
        sync_manifest_from_state()
        emit_meta_changed()

    elif action == "stop_scan":
        is_scanning = False
        logger.info("🛑 Device scanning stopped via UI command.")
        sync_manifest_from_state()
        emit_meta_changed()

    elif action == "select_device":
        is_scanning = False
        new_addr = payload.get("address")
        new_name = payload.get("name")
        if new_addr == "" or new_addr is None:
            target_address = None
            target_name = None
            logger.info("🔓 Device unpaired / target cleared.")
        else:
            target_address = str(new_addr)
            target_name = str(new_name) if new_name else target_address
            logger.info(
                "🔒 Persistent target selected: %s (%s)", target_name, target_address
            )

        sync_manifest_from_state()
        emit_meta_changed()
        if DEVICE_MANIFEST:
            save_overrides(DEVICE_MANIFEST, OVERRIDES_FILE)
            logger.info("💾 Saved device selection to overrides: %s", OVERRIDES_FILE)
        rebind_identity(target_address)

    elif action == "set_unit":
        req_unit = payload.get("unit")
        if req_unit in ("°C", "°F", "C", "F"):
            current_unit = "°F" if "F" in req_unit else "°C"
            logger.info("🔀 Switched temperature unit to %s", current_unit)
            sync_manifest_from_state()
            emit_meta_changed()
            if DEVICE_MANIFEST:
                save_overrides(DEVICE_MANIFEST, OVERRIDES_FILE)


async def ble_scan_loop(simulate: bool) -> None:
    """Async task loop managing physical BLE scanning or simulated sensor emissions."""
    global is_simulated
    if simulate or not HAS_BLEAK:
        is_simulated = True
        if not simulate and not HAS_BLEAK:
            logger.warning(
                "⚠️ 'bleak' library not available. Falling back to simulated Govee sensors."
            )
        logger.info("🎮 Running in SIMULATED Govee Sensor Mode.")

        # Virtual simulated Govee sensors
        virtual_sensors = [
            {
                "address": "A4:C1:38:11:22:33",
                "name": "Govee_LivingRoom",
                "base_temp": 21.5,
                "base_hum": 48.0,
            },
            {
                "address": "A4:C1:38:44:55:66",
                "name": "Govee_Greenhouse",
                "base_temp": 25.8,
                "base_hum": 68.5,
            },
            {
                "address": "A4:C1:38:77:88:99",
                "name": "Govee_Outdoor",
                "base_temp": 14.2,
                "base_hum": 75.0,
            },
        ]

        while True:
            await asyncio.sleep(1.0)
            for sensor in virtual_sensors:
                # Add small random noise to simulated readings
                temp_c = sensor["base_temp"] + random.uniform(-0.15, 0.15)
                humidity = max(
                    0.0, min(100.0, sensor["base_hum"] + random.uniform(-0.3, 0.3))
                )
                rssi = random.randint(-72, -58)
                battery = random.randint(85, 99)
                process_measurement(
                    sensor["address"], sensor["name"], rssi, temp_c, humidity, battery
                )
    else:
        logger.info("📡 Starting physical Govee BLE Scanner...")
        scanner = BleakScanner(ble_detection_callback)
        try:
            await scanner.start()
            while True:
                await asyncio.sleep(2.0)
        except Exception as exc:
            logger.error(
                "❌ Fatal error in BLE Scanner: %s. Switching to fallback simulation mode.",
                exc,
            )
            await ble_scan_loop(simulate=True)
        finally:
            try:
                await scanner.stop()
            except Exception:
                pass


def _persisted_target_address() -> Optional[str]:
    """Read the bound sensor MAC straight from the overrides file.

    The manifest cannot be built first: its task ids depend on the identity,
    which in turn depends on the bound sensor.
    """
    try:
        with open(OVERRIDES_FILE, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    for entry in data.values():
        if not isinstance(entry, dict):
            continue
        address = (entry.get("config") or {}).get("targetAddress")
        if address:
            return str(address)
    return None


def main() -> None:
    """Main execution entry point."""
    global DEVICE_MANIFEST, target_address, target_name, current_unit
    global IDENTITY, DEVICE_ID, PROVIDER_ID, TEMP_TASK_ID, HUMIDITY_TASK_ID, auth

    parser = argparse.ArgumentParser(description="E-Lab Govee Thermo & Hygro Client")
    parser.add_argument(
        "-s",
        "--simulate",
        action="store_true",
        help="Run simulated virtual sensors instead of hardware Bluetooth LE scanning.",
    )
    parser.add_argument(
        "--dispatcher-url",
        type=str,
        default=None,
        help="Direct SocketIO dispatcher URL (bypasses UDP auto-discovery).",
    )
    args = parser.parse_args()

    # 0. Anchor the identity on the previously bound sensor, if any.
    bound = _persisted_target_address()
    if bound:
        IDENTITY = _resolve_identity(bound)
        DEVICE_ID = IDENTITY.device_id
        PROVIDER_ID = DEVICE_ID
        TEMP_TASK_ID = IDENTITY.task_id("temp")
        HUMIDITY_TASK_ID = IDENTITY.task_id("humidity")
        auth = ProviderAuth(DEVICE_ID)

    # 1. Build initial manifest & apply saved persistence overrides
    DEVICE_MANIFEST = create_manifest()
    load_overrides(DEVICE_MANIFEST, OVERRIDES_FILE)

    # Populate state from persisted config if present
    for t in DEVICE_MANIFEST.get("tasks", []):
        cfg = t.get("config", {})
        if cfg.get("targetAddress"):
            target_address = cfg.get("targetAddress")
            target_name = cfg.get("targetName", str(target_address))
        if t.get("id") == TEMP_TASK_ID and cfg.get("unit") in ("°C", "°F"):
            current_unit = cfg.get("unit")

    logger.info(
        "📦 Provider initialized: %s (anchor=%s). Target: %s (%s) | Unit: %s",
        DEVICE_ID,
        IDENTITY.anchor,
        target_name,
        target_address,
        current_unit,
    )

    # 2. Discover dispatcher or use explicit URL
    target_url = args.dispatcher_url or discover_dispatcher(
        UDP_DISCOVERY_PORT, logger, max_attempts=5, timeout_sec=2.0
    )
    if not target_url:
        target_url = "http://localhost:5000"
        logger.warning("⚠️ UDP discovery failed. Defaulting to %s", target_url)

    # 3. Bind authentication & registration and connect SocketIO
    auth.bind(sio)
    try:
        sio.connect(target_url)
        auth.send_register(sio, DEVICE_MANIFEST)
        logger.info("🚀 Successfully registered provider manifest with dispatcher.")
    except Exception as err:
        logger.critical(
            "❌ Could not connect or register with dispatcher at %s: %s",
            target_url,
            err,
        )
        sys.exit(1)

    # 4. Start BLE scanning or simulation in an asyncio loop
    try:
        asyncio.run(ble_scan_loop(simulate=args.simulate))
    except (KeyboardInterrupt, SystemExit):
        logger.info("🛑 Terminating ThermoHygroClient gracefully...")
    finally:
        if sio.connected:
            sio.disconnect()


if __name__ == "__main__":
    main()
