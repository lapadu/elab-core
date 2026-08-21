# pylint: disable=invalid-name
"""
E-Lab client for the OWON XDM1041 digital multimeter.

Supports Voltmeter, Amperemeter, Ohmmeter, and Frequency Counter tasks.
Enforces mutual exclusivity using task groups.
Supports COM port selection via the UI Scanner view and speed/range config.
"""

import time
import json
import socket
import random
import logging
import math
import os
import sys
import argparse
import threading
import urllib.request
import urllib.error
import uuid
from typing import Any, Optional, Dict, Tuple

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

# Add the client directory as an import root so local imports work.
clients_dir = os.path.dirname(os.path.abspath(__file__))
if clients_dir not in sys.path:
    sys.path.insert(0, clients_dir)
if python_clients_root not in sys.path:
    sys.path.insert(0, python_clients_root)

# --- DYNAMIC IMPORTS & ENV DETECTION ---
try:
    from elab_server.manifest_builder import ManifestBuilder
except ImportError:
    # Fallback for alternative layout
    pi_path = os.path.join(project_root, 'shared')
    sys.path.insert(0, pi_path)
    from manifest_builder import ManifestBuilder

try:
    from elab_clients_core.python.shared.discovery import discover_dispatcher
    from elab_clients_core.python.shared.overrides import (
        load_overrides,
        save_overrides,
        apply_task_meta_update,
    )
    from elab_clients_core.python.shared.auth import ProviderAuth
except ImportError:
    from shared.discovery import discover_dispatcher
    from shared.overrides import (
        load_overrides,
        save_overrides,
        apply_task_meta_update,
    )
    from shared.auth import ProviderAuth

# Local wrapper imports
try:
    from elab_clients_core.python.drivers.xdm1041defs import XDM1041Mode, XDM1041Cmd
    from elab_clients_core.python.drivers.xdm1041main import XDM1041
except ImportError:
    try:
        from drivers.xdm1041defs import XDM1041Mode, XDM1041Cmd
        from drivers.xdm1041main import XDM1041
    except ImportError:
        logger = logging.getLogger("Owon XDM1041")
        logger.error("Could not import OWON XDM1041 wrapper. Real hardware will not be accessible.")
        XDM1041 = None
        XDM1041Mode = None

# --- GLOBALS & CONFIG ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(name)s: %(message)s')
logger = logging.getLogger("Owon XDM1041")

DISPATCHER_PORT = 5000
UDP_DISCOVERY_PORT = 5005
DISCOVERY_ATTEMPTS = 3

GUID_FILE = os.path.join(core_clients_dir, "owon_xdm1041_guid.txt")


def get_or_create_guid() -> str:
    """Retrieves a persistent GUID from disk or creates a new UUIDv4 if not existing."""
    if os.path.exists(GUID_FILE):
        try:
            with open(GUID_FILE, "r", encoding="utf-8") as f:
                saved_guid = f.read().strip()
                if saved_guid:
                    return saved_guid
        except Exception as exc:
            logger.warning("Could not read GUID file: %s", exc)

    new_guid = str(uuid.uuid4())
    try:
        os.makedirs(os.path.dirname(GUID_FILE), exist_ok=True)
        with open(GUID_FILE, "w", encoding="utf-8") as f:
            f.write(new_guid)
        logger.info("Created new persistent provider GUID: %s", new_guid)
    except Exception as exc:
        logger.warning("Could not write GUID file: %s", exc)
    return new_guid


PROVIDER_GUID = get_or_create_guid()
DEVICE_ID = f"owon_xdm1041_{PROVIDER_GUID}"
DEVICE_MANIFEST = None
OVERRIDES_FILE = os.path.join(core_clients_dir, 'owon_xdm1041_overrides.json')

SAMPLE_RATE = 2.0  # DMM updates at ~2Hz over serial
CHUNK_SIZE = 1
CHUNK_DURATION = CHUNK_SIZE / SAMPLE_RATE

is_scanning = False
target_address = None
target_name = None
sio = socketio.Client(reconnection=True, reconnection_attempts=10, reconnection_delay=2)
auth = ProviderAuth(DEVICE_ID)


# --- DMM HARDWARE & SIMULATION LOGIC ---
class OwonMultimeterDevice:
    """Handles communication with the physical DMM or falls back to simulation."""
    def __init__(self, port: Optional[str] = None):
        self.port = port
        self.dmm = None
        self.simulated = True
        self._lock = threading.Lock()
        
        if port:
            self.connect_to_port(port)

    def connect_to_port(self, port: str):
        """Connects to the given serial port."""
        with self._lock:
            self.disconnect()
            self.port = port
            if XDM1041 is not None:
                try:
                    logger.info("Connecting to OWON XDM1041 on port %s...", port)
                    self.dmm = XDM1041(XDM1041Mode.MODE_VOLTAGE_DC, 0, port)
                    self.dmm.set_sample_speed_slow()
                    self.simulated = False
                    logger.info("✅ OWON XDM1041 DMM connected successfully!")
                except Exception as e:
                    logger.error("❌ Failed to connect to OWON DMM on %s: %s. Falling back to simulation.", port, e)
                    self.simulated = True
                    self.dmm = None
            else:
                self.simulated = True

    def disconnect(self):
        """Closes serial connection."""
        if self.dmm:
            try:
                self.dmm.disconnect()
            except Exception:
                pass
            self.dmm = None
        self.simulated = True

    def query(self) -> Tuple[str, float]:
        """Queries DMM mode and value."""
        with self._lock:
            if self.simulated or not self.dmm:
                return self._simulate()

            try:
                # Query current function
                self.dmm.send_cmd("FUNC?\n")
                time.sleep(0.05)
                func = self.dmm.read_result().strip().upper()
                
                if not func:
                    # Fallback to CONFIG query
                    self.dmm.send_cmd("CONF?\n")
                    time.sleep(0.05)
                    func = self.dmm.read_result().strip().upper()

                # Read raw value
                val = self.dmm.read_val1_raw()
                return func, val
            except Exception as e:
                logger.error("Error communicating with DMM hardware: %s. Reverting to simulation.", e)
                self.disconnect()
                return "SIMULATED", 0.0

    def _simulate(self) -> Tuple[str, Tuple[float, float, float, float, float, float, float]]:
        """Simulates values."""
        t = time.time()
        sim_volt_dc = 5.0 * math.sin(t * 0.1) + random.uniform(-0.01, 0.01)
        sim_volt_ac = abs(12.0 * math.sin(t * 0.15) + random.uniform(-0.05, 0.05))
        sim_curr_dc = 1.5 + random.uniform(-0.005, 0.005)
        sim_curr_ac = abs(0.8 * math.sin(t * 0.05) + random.uniform(-0.002, 0.002))
        sim_ohm = 4700.0 + random.uniform(-1.0, 1.0)
        sim_freq = 50.0 + random.uniform(-0.02, 0.02)
        sim_cap = 100e-6 + random.uniform(-1e-7, 1e-7)  # 100 µF
        
        return "SIMULATED", (sim_volt_dc, sim_volt_ac, sim_curr_dc, sim_curr_ac, sim_ohm, sim_freq, sim_cap)


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


device = OwonMultimeterDevice()


def sync_manifest_from_state() -> None:
    """Synchronizes global port config into all task states."""
    global DEVICE_MANIFEST, target_address, target_name, is_scanning
    if not DEVICE_MANIFEST:
        return
    for task in DEVICE_MANIFEST.get("tasks", []):
        cfg = task.setdefault("config", {})
        cfg["targetAddress"] = target_address
        cfg["targetName"] = target_name or ("No COM Port Selected" if not target_address else str(target_address))
        cfg["isScanning"] = is_scanning


def sync_state_from_manifest() -> None:
    """Syncs target_address and name from manifest configuration."""
    global target_address, target_name, DEVICE_MANIFEST
    if DEVICE_MANIFEST and DEVICE_MANIFEST.get("tasks"):
        cfg = DEVICE_MANIFEST["tasks"][0].get("config", {})
        target_address = cfg.get("targetAddress")
        target_name = cfg.get("targetName")


def emit_meta_changed() -> None:
    """Broadcasts metadata updates to the dispatcher server."""
    if not sio.connected or not DEVICE_MANIFEST:
        return
    for task in DEVICE_MANIFEST.get("tasks", []):
        t_id = task["id"]
        cfg_update = {
            "targetAddress": target_address,
            "targetName": target_name or ("No COM Port Selected" if not target_address else str(target_address)),
            "isScanning": is_scanning,
            "discoveredDevices": task.get("config", {}).get("discoveredDevices", [])
        }
        # Copy other config values (like speed/range indices)
        for key in ["sample_speed", "range_idx"]:
            if key in task.get("config", {}):
                cfg_update[key] = task["config"][key]
                
        try:
            sio.emit(
                "provider_meta_changed",
                {"task_id": t_id, "changes": {"config": cfg_update}}
            )
        except Exception as e:
            logger.debug("Failed emitting meta changed: %s", e)


def build_manifest(schema_dict=None):
    """Builds the device manifest with mutually exclusive tasks."""
    global DEVICE_MANIFEST
    logger.info("🛠️ Building device manifest...")
    builder = ManifestBuilder(DEVICE_ID, "OWON XDM1041 Multimeter", schema_dict=schema_dict)
    
    # 1. Voltage Task (DC/AC selectable)
    builder.add_task(
        task_id=f"{DEVICE_ID}_volt",
        name="Voltage",
        task_type="SENSOR",
        group_id="owon_xdm1041_v1",
        group="voltmeter_group",
        virtual=False,
        color="#ef4444",
        config={
            "range": [-1000, 1000],
            "unit": "V",
            "targetAddress": None,
            "targetName": "No COM Port Selected",
            "isScanning": False,
            "discoveredDevices": [],
            "sample_speed": "slow",
            "range_idx": 0,
            "ac_dc": "DC",
            "configFields": [
                {
                    "key": "ac_dc",
                    "label": "Mode",
                    "type": "select",
                    "value": "DC",
                    "options": [
                        {"value": "DC", "label": "DC"},
                        {"value": "AC", "label": "AC"}
                    ]
                },
                {
                    "key": "sample_speed",
                    "label": "Measurement Speed",
                    "type": "select",
                    "value": "slow",
                    "options": [
                        {"value": "slow", "label": "Slow (Low)"},
                        {"value": "med", "label": "Medium (Med)"},
                        {"value": "fast", "label": "Fast (High)"}
                    ]
                },
                {
                    "key": "range_idx",
                    "label": "Range",
                    "type": "select",
                    "value": 0,
                    "options": [
                        {"value": 0, "label": "Auto"},
                        {"value": 1, "label": "50mV"},
                        {"value": 2, "label": "500mV"},
                        {"value": 3, "label": "5V"},
                        {"value": 4, "label": "50V"},
                        {"value": 5, "label": "500V"},
                        {"value": 6, "label": "1000V"}
                    ]
                }
            ],
            "accuracy": {
                "model": "percent_reading_plus_digits",
                "relativePctReading": 0.05,
                "digits": 2,
                "digitReference": "ui_lsd",
                "displayStep": 0.0001,
                "confidenceK": 2.0,
            }
        },
        ui_mode="generic",
        ui_default_template="tpl_metric",
        ui_views=[
            {
                "id": "metric",
                "label": "Metric",
                "icon": "Maximize2",
                "template": "tpl_metric",
            },
            {
                "id": "config",
                "label": "Scanner",
                "icon": "Radio",
                "template": "tpl_device_scanner_config",
            }
        ]
    )
    
    # 2. Current Task (DC/AC selectable)
    builder.add_task(
        task_id=f"{DEVICE_ID}_curr",
        name="Current",
        task_type="SENSOR",
        group_id="owon_xdm1041_v1",
        group="amperemeter_group",
        virtual=False,
        color="#3b82f6",
        config={
            "range": [-10, 10],
            "unit": "A",
            "targetAddress": None,
            "targetName": "No COM Port Selected",
            "isScanning": False,
            "discoveredDevices": [],
            "sample_speed": "slow",
            "range_idx": 0,
            "ac_dc": "DC",
            "configFields": [
                {
                    "key": "ac_dc",
                    "label": "Mode",
                    "type": "select",
                    "value": "DC",
                    "options": [
                        {"value": "DC", "label": "DC"},
                        {"value": "AC", "label": "AC"}
                    ]
                },
                {
                    "key": "sample_speed",
                    "label": "Measurement Speed",
                    "type": "select",
                    "value": "slow",
                    "options": [
                        {"value": "slow", "label": "Slow (Low)"},
                        {"value": "med", "label": "Medium (Med)"},
                        {"value": "fast", "label": "Fast (High)"}
                    ]
                },
                {
                    "key": "range_idx",
                    "label": "Range",
                    "type": "select",
                    "value": 0,
                    "options": [
                        {"value": 0, "label": "Auto"},
                        {"value": 1, "label": "500µA"},
                        {"value": 2, "label": "5mA"},
                        {"value": 3, "label": "50mA"},
                        {"value": 4, "label": "500mA"},
                        {"value": 5, "label": "5A"},
                        {"value": 6, "label": "10A"}
                    ]
                }
            ],
            "accuracy": {
                "model": "percent_reading_plus_digits",
                "relativePctReading": 0.15,
                "digits": 5,
                "digitReference": "ui_lsd",
                "displayStep": 0.00001,
                "confidenceK": 2.0,
            }
        },
        ui_mode="generic",
        ui_default_template="tpl_metric",
        ui_views=[
            {
                "id": "metric",
                "label": "Metric",
                "icon": "Maximize2",
                "template": "tpl_metric",
            },
            {
                "id": "config",
                "label": "Scanner",
                "icon": "Radio",
                "template": "tpl_device_scanner_config",
            }
        ]
    )
    
    # 3. Resistance Task
    builder.add_task(
        task_id=f"{DEVICE_ID}_ohm",
        name="Resistance",
        task_type="SENSOR",
        group_id="owon_xdm1041_v1",
        group="ohmmeter_group",
        virtual=False,
        color="#10b981",
        config={
            "range": [0, 50000000],
            "unit": "Ω",
            "targetAddress": None,
            "targetName": "No COM Port Selected",
            "isScanning": False,
            "discoveredDevices": [],
            "sample_speed": "slow",
            "range_idx": 0,
            "configFields": [
                {
                    "key": "sample_speed",
                    "label": "Measurement Speed",
                    "type": "select",
                    "value": "slow",
                    "options": [
                        {"value": "slow", "label": "Slow (Low)"},
                        {"value": "med", "label": "Medium (Med)"},
                        {"value": "fast", "label": "Fast (High)"}
                    ]
                },
                {
                    "key": "range_idx",
                    "label": "Range",
                    "type": "select",
                    "value": 0,
                    "options": [
                        {"value": 0, "label": "Auto"},
                        {"value": 1, "label": "500Ω"},
                        {"value": 2, "label": "5kΩ"},
                        {"value": 3, "label": "50kΩ"},
                        {"value": 4, "label": "500kΩ"},
                        {"value": 5, "label": "5MΩ"},
                        {"value": 6, "label": "50MΩ"}
                    ]
                }
            ],
            "accuracy": {
                "model": "percent_reading_plus_digits",
                "relativePctReading": 0.1,
                "digits": 3,
                "digitReference": "ui_lsd",
                "displayStep": 0.1,
                "confidenceK": 2.0,
            }
        },
        ui_mode="generic",
        ui_default_template="tpl_metric",
        ui_views=[
            {
                "id": "metric",
                "label": "Metric",
                "icon": "Maximize2",
                "template": "tpl_metric",
            },
            {
                "id": "config",
                "label": "Scanner",
                "icon": "Radio",
                "template": "tpl_device_scanner_config",
            }
        ]
    )
    
    # 4. Frequency Task
    builder.add_task(
        task_id=f"{DEVICE_ID}_freq",
        name="Frequency",
        task_type="SENSOR",
        group_id="owon_xdm1041_v1",
        group="frequency_group",
        virtual=False,
        color="#f59e0b",
        config={
            "range": [0, 60000000],
            "unit": "Hz",
            "targetAddress": None,
            "targetName": "No COM Port Selected",
            "isScanning": False,
            "discoveredDevices": [],
            "configFields": [],
            "accuracy": {
                "model": "percent_reading_plus_digits",
                "relativePctReading": 0.01,
                "digits": 1,
                "digitReference": "ui_lsd",
                "displayStep": 0.01,
                "confidenceK": 2.0,
            }
        },
        ui_mode="generic",
        ui_default_template="tpl_metric",
        ui_views=[
            {
                "id": "metric",
                "label": "Metric",
                "icon": "Maximize2",
                "template": "tpl_metric",
            },
            {
                "id": "config",
                "label": "Scanner",
                "icon": "Radio",
                "template": "tpl_device_scanner_config",
            }
        ]
    )

    # 5. Capacitance Task
    builder.add_task(
        task_id=f"{DEVICE_ID}_cap",
        name="Capacitance",
        task_type="SENSOR",
        group_id="owon_xdm1041_v1",
        group="capacitance_group",
        virtual=False,
        color="#8b5cf6",
        config={
            "range": [0, 0.05],
            "unit": "F",
            "targetAddress": None,
            "targetName": "No COM Port Selected",
            "isScanning": False,
            "discoveredDevices": [],
            "range_idx": 0,
            "configFields": [
                {
                    "key": "range_idx",
                    "label": "Range",
                    "type": "select",
                    "value": 0,
                    "options": [
                        {"value": 0, "label": "Auto"},
                        {"value": 1, "label": "50nF"},
                        {"value": 2, "label": "500nF"},
                        {"value": 3, "label": "5µF"},
                        {"value": 4, "label": "50µF"},
                        {"value": 5, "label": "500µF"},
                        {"value": 6, "label": "5mF"},
                        {"value": 7, "label": "50mF"}
                    ]
                }
            ],
            "accuracy": {
                "model": "percent_reading_plus_digits",
                "relativePctReading": 1.0,
                "digits": 5,
                "digitReference": "ui_lsd",
                "displayStep": 0.000000001,
                "confidenceK": 2.0,
            }
        },
        ui_mode="generic",
        ui_default_template="tpl_metric",
        ui_views=[
            {
                "id": "metric",
                "label": "Metric",
                "icon": "Maximize2",
                "template": "tpl_metric",
            },
            {
                "id": "config",
                "label": "Scanner",
                "icon": "Radio",
                "template": "tpl_device_scanner_config",
            }
        ]
    )

    try:
        DEVICE_MANIFEST = builder.build()
        logger.info("✅ Manifest built and validated successfully.")
        load_overrides(DEVICE_MANIFEST, OVERRIDES_FILE)
    except Exception as e:
        logger.error("💥 Failed to build manifest: %s", e)
        DEVICE_MANIFEST = None


# --- MEASUREMENT LOOP ---
def measurement_loop(device: OwonMultimeterDevice, send_callback):
    """Reads data from DMM/simulation and forwards to dispatcher."""
    logger.info("🚀 Starting DMM Measurement Loop (~%.1f Hz)...", SAMPLE_RATE)
    
    while True:
        loop_start = time.time()
        try:
            now_ts = loop_start
            start_ts = now_ts - CHUNK_DURATION
            
            func, val = device.query()
            
            if func == "SIMULATED":
                # Get ac_dc mode from global manifest
                volt_ac_dc = "DC"
                curr_ac_dc = "DC"
                if DEVICE_MANIFEST:
                    for task in DEVICE_MANIFEST.get("tasks", []):
                        if task["id"].endswith("_volt"):
                            volt_ac_dc = task.get("config", {}).get("ac_dc", "DC")
                        elif task["id"].endswith("_curr"):
                            curr_ac_dc = task.get("config", {}).get("ac_dc", "DC")

                v_volt_dc, v_volt_ac, v_curr_dc, v_curr_ac, v_ohm, v_freq, v_cap = val
                
                payloads = [
                    (f"{DEVICE_ID}_volt", v_volt_ac if volt_ac_dc == "AC" else v_volt_dc),
                    (f"{DEVICE_ID}_curr", v_curr_ac if curr_ac_dc == "AC" else v_curr_dc),
                    (f"{DEVICE_ID}_ohm", v_ohm),
                    (f"{DEVICE_ID}_freq", v_freq),
                    (f"{DEVICE_ID}_cap", v_cap)
                ]
                for source_id, value in payloads:
                    payload = {
                        "sourceId": source_id,
                        "values": [value],
                        "distribution": "linear",
                        "startTime": start_ts * 1000,
                        "endTime": now_ts * 1000,
                        "timestamp": now_ts * 1000,
                        "value": value
                    }
                    send_callback(payload)
            else:
                # Hardware mode: match function to correct task
                target_task = None
                if "VOLT" in func:
                    target_task = "volt"
                elif "CURR" in func or "AMP" in func:
                    target_task = "curr"
                elif "RES" in func or "OHM" in func:
                    target_task = "ohm"
                elif "FREQ" in func:
                    target_task = "freq"
                elif "CAP" in func:
                    target_task = "cap"
                
                if target_task:
                    payload = {
                        "sourceId": f"{DEVICE_ID}_{target_task}",
                        "values": [val],
                        "distribution": "linear",
                        "startTime": start_ts * 1000,
                        "endTime": now_ts * 1000,
                        "timestamp": now_ts * 1000,
                        "value": val
                    }
                    send_callback(payload)
                else:
                    logger.warning("Unmapped DMM mode received: %s", func)
                    
        except Exception as e:
            logger.error("💥 Error in DMM measurement loop: %s", e)
            time.sleep(CHUNK_DURATION)
            continue
            
        finally:
            elapsed = time.time() - loop_start
            sleep_time = max(0, CHUNK_DURATION - elapsed)
            time.sleep(sleep_time)


# --- DISPATCHER CONNECTION ---
def run_dispatcher_mode(dispatcher_url, device: OwonMultimeterDevice):
    """Starts the client in dispatcher mode."""
    logger.info("🔗 Connecting to dispatcher: %s", dispatcher_url)
    upstream_connected = threading.Event()

    auth.bind(sio)

    @sio.event
    def connect():
        upstream_connected.set()
        logger.info("✅ Connected to Upstream Dispatcher!")
        auth.send_register(sio, DEVICE_MANIFEST)

    @sio.event
    def disconnect():
        upstream_connected.clear()
        logger.warning("⚠️ Disconnected from Upstream Dispatcher")

    @sio.event
    def execute_command(data):
        global is_scanning, target_address, target_name, device
        if not isinstance(data, dict):
            return

        target_id = str(data.get("provider_id", "")).replace("prov_", "")
        task_ids = {t["id"] for t in DEVICE_MANIFEST.get("tasks", [])} if DEVICE_MANIFEST else set()
        if target_id not in task_ids and target_id != DEVICE_ID:
            return

        command = data.get("command", {})
        action = command.get("action")
        payload = command.get("payload", {})

        logger.info("📥 Received command action='%s', payload=%r", action, payload)

        if action == "start_scan":
            is_scanning = True
            logger.info("🔍 Serial port scanning started via UI command.")
            
            # Scan ports
            import serial.tools.list_ports
            ports = serial.tools.list_ports.comports()
            discovered_devices = []
            for p in ports:
                discovered_devices.append({
                    "address": p.device,
                    "name": f"USB-SERIAL ({p.device})" if "CH340" in p.description or "Prolific" in p.description or "USB-SERIAL" in p.description.upper() else p.description,
                    "rssi": None
                })
            
            # If empty, add mock entries so the user can test DMM selection
            if not discovered_devices:
                discovered_devices.append({
                    "address": "COM29",
                    "name": "Simulated Multimeter Port (COM29)",
                    "rssi": None
                })
                discovered_devices.append({
                    "address": "COM3",
                    "name": "Simulated COM3",
                    "rssi": None
                })

            for task in DEVICE_MANIFEST.get("tasks", []):
                cfg = task.setdefault("config", {})
                cfg["discoveredDevices"] = discovered_devices
                cfg["isScanning"] = True
            
            emit_meta_changed()

        elif action == "stop_scan":
            is_scanning = False
            for task in DEVICE_MANIFEST.get("tasks", []):
                cfg = task.setdefault("config", {})
                cfg["isScanning"] = False
            emit_meta_changed()

        elif action == "select_device":
            is_scanning = False
            new_addr = payload.get("address")
            new_name = payload.get("name")
            
            if not new_addr:
                target_address = None
                target_name = None
                logger.info("🔓 COM port cleared.")
                device.disconnect()
            else:
                target_address = str(new_addr)
                target_name = str(new_name) if new_name else target_address
                logger.info("🔒 Persistent COM port selected: %s (%s)", target_name, target_address)
                device.connect_to_port(target_address)

            for task in DEVICE_MANIFEST.get("tasks", []):
                cfg = task.setdefault("config", {})
                cfg["targetAddress"] = target_address
                cfg["targetName"] = target_name or "No COM Port Selected"
                cfg["isScanning"] = False
                cfg["simulated"] = device.simulated
                
            emit_meta_changed()
            if DEVICE_MANIFEST:
                save_overrides(DEVICE_MANIFEST, OVERRIDES_FILE)
                logger.info("💾 Saved DMM port to overrides: %s", OVERRIDES_FILE)
                


        elif action == "update_config":
            for key, val in payload.items():
                for task in DEVICE_MANIFEST.get("tasks", []):
                    if task["id"] == target_id:
                        task.setdefault("config", {})[key] = val
                        
                        # Dynamically update Voltage range options when mode (ac_dc) changes
                        if task["id"].endswith("_volt") and key == "ac_dc":
                            for field in task["config"].get("configFields", []):
                                if field["key"] == "range_idx":
                                    if val == "AC":
                                        field["options"] = [
                                            {"value": 0, "label": "Auto"},
                                            {"value": 1, "label": "500mV"},
                                            {"value": 2, "label": "5V"},
                                            {"value": 3, "label": "50V"},
                                            {"value": 4, "label": "500V"},
                                            {"value": 5, "label": "750V"}
                                        ]
                                    else:
                                        field["options"] = [
                                            {"value": 0, "label": "Auto"},
                                            {"value": 1, "label": "50mV"},
                                            {"value": 2, "label": "500mV"},
                                            {"value": 3, "label": "5V"},
                                            {"value": 4, "label": "50V"},
                                            {"value": 5, "label": "500V"},
                                            {"value": 6, "label": "1000V"}
                                        ]

                logger.info("⚙️ Configuration updated for %s: %s = %s", target_id, key, val)
                
                if not device.simulated and device.dmm:
                    try:
                        # Determine DMM mode based on ac_dc config and task_id
                        t_cfg = None
                        for task in DEVICE_MANIFEST.get("tasks", []):
                            if task["id"] == target_id:
                                t_cfg = task.get("config", {})
                                break
                        
                        ac_dc_mode = t_cfg.get("ac_dc", "DC") if t_cfg else "DC"
                        
                        target_mode = None
                        if target_id.endswith("_volt"):
                            if ac_dc_mode == "AC":
                                target_mode = XDM1041Mode.MODE_VOLTAGE_AC if XDM1041Mode else None
                            else:
                                target_mode = XDM1041Mode.MODE_VOLTAGE_DC if XDM1041Mode else None
                        elif target_id.endswith("_curr"):
                            if ac_dc_mode == "AC":
                                target_mode = XDM1041Mode.MODE_CURRENT_AC if XDM1041Mode else None
                            else:
                                target_mode = XDM1041Mode.MODE_CURRENT_DC if XDM1041Mode else None
                        elif target_id.endswith("_ohm"):
                            target_mode = XDM1041Mode.MODE_RES if XDM1041Mode else None
                        elif target_id.endswith("_freq"):
                            target_mode = XDM1041Mode.MODE_FREQUENCY if XDM1041Mode else None
                        elif target_id.endswith("_cap"):
                            target_mode = XDM1041Mode.MODE_CAPACITANCE if XDM1041Mode else None

                        if target_mode:
                            device.dmm.set_mode(target_mode)
                            device.dmm.mode = target_mode
                            time.sleep(0.1)

                        if key == "sample_speed":
                            if val == "slow":
                                device.dmm.set_sample_speed_slow()
                            elif val == "med":
                                device.dmm.set_sample_speed_med()
                            elif val == "fast":
                                device.dmm.set_sample_speed_fast()
                        elif key == "range_idx":
                            if val == 0:
                                device.dmm.send_cmd(str(XDM1041Cmd.SET_AUTO_MODE))
                            else:
                                device.dmm.set_range(int(val))
                    except Exception as ex:
                        logger.error("Error applying config to DMM: %s", ex)
                        
            emit_meta_changed()
            if DEVICE_MANIFEST:
                save_overrides(DEVICE_MANIFEST, OVERRIDES_FILE)

        elif action == "execute_task":
            # Switch DMM mode when task is assigned to slot
            task_id = payload.get("task_id")
            if not task_id:
                return
            logger.info("🎯 Task execution started: %s", task_id)
            
            t_cfg = None
            for task in DEVICE_MANIFEST.get("tasks", []):
                if task["id"] == task_id:
                    t_cfg = task.get("config", {})
                    break
            
            ac_dc_mode = t_cfg.get("ac_dc", "DC") if t_cfg else "DC"
            
            target_mode = None
            if task_id.endswith("_volt"):
                if ac_dc_mode == "AC":
                    target_mode = XDM1041Mode.MODE_VOLTAGE_AC if XDM1041Mode else None
                else:
                    target_mode = XDM1041Mode.MODE_VOLTAGE_DC if XDM1041Mode else None
            elif task_id.endswith("_curr"):
                if ac_dc_mode == "AC":
                    target_mode = XDM1041Mode.MODE_CURRENT_AC if XDM1041Mode else None
                else:
                    target_mode = XDM1041Mode.MODE_CURRENT_DC if XDM1041Mode else None
            elif task_id.endswith("_ohm"):
                target_mode = XDM1041Mode.MODE_RES if XDM1041Mode else None
            elif task_id.endswith("_freq"):
                target_mode = XDM1041Mode.MODE_FREQUENCY if XDM1041Mode else None
            elif task_id.endswith("_cap"):
                target_mode = XDM1041Mode.MODE_CAPACITANCE if XDM1041Mode else None

            if not device.simulated and device.dmm and target_mode:
                try:
                    logger.info("🔌 Switching DMM physical mode to match active task: %s", target_mode)
                    device.dmm.set_mode(target_mode)
                    device.dmm.mode = target_mode
                except Exception as ex:
                    logger.error("Failed to switch DMM mode: %s", ex)

        elif action == 'update_meta':
            # Handle overrides synchronization
            payload = command.get('payload', {})
            logger.debug("🎨 UI requested meta update: %s", payload)

            if DEVICE_MANIFEST is None:
                return
            target_id = data.get('provider_id', '').replace('prov_', '')
            if apply_task_meta_update(DEVICE_MANIFEST, target_id, payload):
                save_overrides(DEVICE_MANIFEST, OVERRIDES_FILE)

    def safe_send(payload):
        if sio.connected and auth.has_secret():
            try:
                sio.emit('data_stream', auth.sign(payload))
            except Exception as e:
                logger.debug("Send error: %s", e)

    try:
        sio.connect(dispatcher_url)
        measurement_loop(device, safe_send)
    except socketio.exceptions.ConnectionError as e:
        logger.error("❌ Connection failed: %s", e)


def run_standalone_mode(device: OwonMultimeterDevice):
    """Starts the client in standalone mode with a local server."""
    logger.info("🏠 Starting in STANDALONE MODE (Local Webserver)")
    
    app = Flask(__name__)
    CORS(app)
    local_server = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

    @local_server.on('connect')
    def handle_local_connect():
        logger.info("💻 Local Browser connected!")
        local_server.emit('available_providers', {'providers': [DEVICE_MANIFEST]})

    local_server.start_background_task(
        measurement_loop,
        device,
        lambda payload: local_server.emit('data_stream', payload)
    )

    port = 8085
    logger.info("🌐 Web UI available at http://%s:%s", get_local_ip(), port)
    local_server.run(app, host='0.0.0.0', port=port, debug=False, allow_unsafe_werkzeug=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='E-Lab OWON XDM1041 Multimeter Client')
    parser.add_argument('--port', type=str, help='Serial port for OWON XDM1041 (e.g. COM3 or /dev/ttyUSB0).')
    parser.add_argument('--server-ip', type=str, help='Manually specify the server IP to bypass UDP discovery.')
    args = parser.parse_args()

    DISPATCHER_URL = None
    schema = None

    if args.server_ip:
        logger.info("🔩 Manual server IP provided: %s", args.server_ip)
        DISPATCHER_URL = f"http://{args.server_ip}:{DISPATCHER_PORT}"
        try:
            with urllib.request.urlopen(f"{DISPATCHER_URL}/schemas/ManifestSchema.json", timeout=5) as response:
                if response.status == 200:
                    schema = json.loads(response.read().decode('utf-8'))
        except Exception:
            pass
    else:
        logger.info("🌐 Automatic discovery mode.")
        for i in range(DISCOVERY_ATTEMPTS):
            logger.info("🔄 Connection Attempt %d/%d...", i + 1, DISCOVERY_ATTEMPTS)
            DISPATCHER_URL = discover_dispatcher(UDP_DISCOVERY_PORT, logger, max_attempts=1, timeout_sec=2.0)
            if DISPATCHER_URL:
                try:
                    with urllib.request.urlopen(f"{DISPATCHER_URL}/schemas/ManifestSchema.json", timeout=5) as response:
                        if response.status == 200:
                            schema = json.loads(response.read().decode('utf-8'))
                except Exception:
                    pass
                break

    # Build manifest
    build_manifest(schema_dict=schema)
    
    # Load port config from persistent manifest overrides
    sync_state_from_manifest()
    

    
    # CLI arg overrides saved value
    if args.port:
        target_address = args.port
        target_name = f"COM Port ({args.port})"
        if DEVICE_MANIFEST:
            for task in DEVICE_MANIFEST.get("tasks", []):
                cfg = task.setdefault("config", {})
                cfg["targetAddress"] = target_address
                cfg["targetName"] = target_name
            save_overrides(DEVICE_MANIFEST, OVERRIDES_FILE)

    # Initialize multimeter connection with loaded/provided port
    device.connect_to_port(target_address)

    # Set simulated flag for all tasks
    if DEVICE_MANIFEST:
        for task in DEVICE_MANIFEST.get("tasks", []):
            task.setdefault("config", {})["simulated"] = device.simulated

    if DISPATCHER_URL:
        if DEVICE_MANIFEST:
            run_dispatcher_mode(DISPATCHER_URL, device)
        else:
            logger.error("❌ Exiting: Manifest could not be built.")
    else:
        logger.warning("⚠️ No Dispatcher found. Running in standalone mode.")
        if DEVICE_MANIFEST:
            run_standalone_mode(device)
        else:
            logger.error("❌ Exiting: Manifest could not be built.")
