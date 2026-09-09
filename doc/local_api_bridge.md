# Local API Bridge - User Guide

The **Local API Bridge** allows external Python scripts to integrate seamlessly with the E-Lab ecosystem. Using a hybrid IPC approach (ZeroMQ + shared memory), scripts can process high-frequency data streams, send control signals, and provide native UI widgets in the React workbench without writing frontend code.

## Python Scripts and UI Plugins

A Python script using `elab_api` and a UI plugin are two different components:

| Component | Runs where? | Purpose | Connection to the Bridge |
|---|---|---|---|
| Python script (`elab_api`) | As a separate Python process | Registers tasks, processes data, publishes measurements, and reacts to UI configuration | Direct connection to the Bridge Daemon through ZeroMQ and shared memory |
| Generic widget | In the React workbench | Displays a registered task based on `template` and `config` | No separate connection; the workbench handles data communication |
| JavaScript UI plugin (`ui_mode="custom"`) | In the browser inside the workbench | Replaces or extends the presentation of a task | No direct ZeroMQ or shared-memory connection; the plugin receives data and actions through the workbench plugin API |

A UI plugin is therefore **not an alternative Python client** and does not replace
`LocalNode` or the Bridge Daemon. It is only an optional presentation layer for a
task registered by a Python script or another provider. A generic widget is
sufficient for most sensors and actuators. See [plugin_development.md](plugin_development.md)
for JavaScript plugins.

## Requirements

Install from the project root (editable mode is recommended for development):

```bash
pip install -e .
```

After installation, `elab_api` and `elab_bridge` can be imported from anywhere in the same Python environment.

Alternative without an editable install:

```bash
pip install .
```

Additional direct dependencies (if only individual modules are installed):

```bash
pip install pyzmq numpy
```

For DSP applications, also install:

```bash
pip install scipy
```

## Architecture

```
External script  ←─ ZMQ + SHM ─→  Bridge Daemon  ←─ Socket.IO ─→  Dispatcher
  (elab_api)                        (elab_bridge)                   (server.py)
```

| Layer | Transport | Purpose |
|-------|-----------|-------|
| **Control Plane** | ZeroMQ (REQ/REP, port 5580) | Registration, configuration updates, and actuator commands |
| **Notification** | ZeroMQ (PUB/SUB, port 5581) | Async events from the dispatcher to the script |
| **Data Plane** | Shared memory (ring buffer) | Zero-copy NumPy streaming (≤ 1 ms latency) |

## Quickstart

### 1. Start the Bridge Daemon

```bash
python -m elab_bridge.bridge_daemon --dispatcher-url http://127.0.0.1:5000
```

Or use the console script entry point (after `pip install -e .`):

```bash
elab-bridge-daemon --dispatcher-url http://127.0.0.1:5000
```

### 2. Run an external script

```python
from elab_api import LocalNode

node = LocalNode(name="My Script")
node.register_task(task_id="output", task_type="SENSOR", template="tpl_generic_sensor")
node.run()
```

To define the device identity of a Python script explicitly, use
`DeviceDefinition` as well:

```python
from elab_api import DeviceDefinition, LocalNode

node = LocalNode(
    name="My Script",
    device=DeviceDefinition(
        device_id="lab_script_01",
        model="fir_filter",
        anchor="assigned",
        firmware_version="1.0.0",
    ),
)
```

---

## Complete Example: FIR Filter Node

The following script implements a configurable FIR low-pass filter. It subscribes to a raw data stream (for example, from an ESP32 voltmeter), applies the filter, and publishes the filtered signal as a new virtual sensor in the workbench.

```python
"""FIR filter node for E-Lab.

Subscribes to a raw data stream, applies a configurable FIR filter,
and publishes the filtered signal as a new virtual sensor.
"""
import numpy as np
from scipy.signal import firwin, lfilter
from elab_api import LocalNode

# --- Configuration ---
SOURCE_TASK = "esp32_voltmeter_raw"   # Raw data source (task ID in the dispatcher)
OUTPUT_TASK = "fir_filtered_signal"
INITIAL_CUTOFF = 100       # Hz
INITIAL_ORDER = 51         # Number of coefficients
SAMPLE_RATE = 10000        # Hz (must match the source)

# --- Filter state ---
fir_coeffs = firwin(INITIAL_ORDER, INITIAL_CUTOFF, fs=SAMPLE_RATE)
filter_state = np.zeros(INITIAL_ORDER - 1)


def rebuild_filter(order: int, cutoff: float) -> None:
    """Recalculate the FIR coefficients."""
    global fir_coeffs, filter_state
    fir_coeffs = firwin(order, cutoff, fs=SAMPLE_RATE)
    filter_state = np.zeros(order - 1)


# --- Node setup ---
node = LocalNode(name="FIR Lowpass Filter")

# Register the task with native E-Lab configFields (no frontend code required).
node.register_task(
    task_id=OUTPUT_TASK,
    task_type="MATH",
    template="tpl_generic_sensor",
    unit="V",
    sample_rate=SAMPLE_RATE,
    color="#3b82f6",
    tags=["dsp", "filter", "fir"],
    config=[
        {
            "key": "cutoff_freq",
            "label": "Cutoff frequency",
            "type": "slider",
            "value": INITIAL_CUTOFF,
            "min": 10,
            "max": SAMPLE_RATE // 2 - 1,
            "step": 10,
            "unit": "Hz",
        },
        {
            "key": "filter_order",
            "label": "Filter order",
            "type": "number",
            "value": INITIAL_ORDER,
            "min": 5,
            "max": 255,
            "step": 2,
        },
        {
            "key": "filter_type",
            "label": "Window function",
            "type": "select",
            "value": "hamming",
            "options": [
                {"label": "Hamming", "value": "hamming"},
                {"label": "Hann", "value": "hann"},
                {"label": "Blackman", "value": "blackman"},
                {"label": "Rectangular", "value": "boxcar"},
            ],
        },
        {
            "key": "enabled",
            "label": "Filter enabled",
            "type": "toggle",
            "value": True,
        },
    ],
)


# --- Callbacks ---
@node.on_config_update(OUTPUT_TASK)
def on_config_changed(key: str, value):
    """Called when the user changes a parameter in the UI."""
    global fir_coeffs, filter_state, INITIAL_CUTOFF, INITIAL_ORDER

    if key == "cutoff_freq":
        INITIAL_CUTOFF = int(value)
        rebuild_filter(INITIAL_ORDER, INITIAL_CUTOFF)
        print(f"Cutoff changed: {INITIAL_CUTOFF} Hz")

    elif key == "filter_order":
        INITIAL_ORDER = int(value)
        rebuild_filter(INITIAL_ORDER, INITIAL_CUTOFF)
        print(f"Order changed: {INITIAL_ORDER} taps")

    elif key == "filter_type":
        fir_coeffs = firwin(INITIAL_ORDER, INITIAL_CUTOFF,
                            fs=SAMPLE_RATE, window=str(value))
        filter_state = np.zeros(INITIAL_ORDER - 1)
        print(f"Window function changed: {value}")

    elif key == "enabled":
        print(f"Filter {'enabled' if value else 'disabled'}")


@node.on_stream(SOURCE_TASK)
def process_chunk(data: np.ndarray):
    """Process incoming raw data chunks (zero-copy through shared memory)."""
    global filter_state

    # Apply the FIR filter while preserving state across chunk boundaries.
    filtered, filter_state = lfilter(fir_coeffs, 1.0, data, zi=filter_state)

    # Publish the filtered signal; it appears as a new sensor in the UI.
    node.publish(OUTPUT_TASK, filtered.astype(np.float32))


# --- Start ---
if __name__ == "__main__":
    print("FIR filter node started")
    print(f"  Source: {SOURCE_TASK}")
    print(f"  Output: {OUTPUT_TASK}")
    print(f"  Cutoff: {INITIAL_CUTOFF} Hz / order: {INITIAL_ORDER}")
    node.run()
```

### Run the example

```bash
# 1. Start the E-Lab dispatcher
python server.py

# 2. Start the Bridge Daemon
python -m elab_bridge.bridge_daemon

# 3. Run the FIR filter script
python elab_clients_core/python/api/fir_filter_node.py
```

After startup, the `fir_filtered_signal` task appears automatically in the workbench. The user can drag the widget onto the grid and adjust the filter parameters (cutoff, order, and window) live through the generated sliders and select controls.

---

## API Reference

### `LocalNode(name, bridge_host, control_port, notify_port, device, ...)`

| Parameter | Default | Beschreibung |
|-----------|---------|--------------|
| `name` | - | Display name in the UI |
| `bridge_host` | `"127.0.0.1"` | Bridge Daemon host |
| `control_port` | `5580` | ZMQ REQ/REP port |
| `notify_port` | `5581` | ZMQ PUB/SUB port |
| `device` | automatic | Optional `DeviceDefinition` for persistent device identity |
| `category` | `"VIRTUAL_SCRIPT"` | Provider category in the manifest |
| `provider_version` | `"1.0.0"` | Python provider version |
| `api_version` | `"2.1.0"` | E-Lab API version in use |
| `persist_config` | `False` | Whether the provider persists configuration itself |

### `node.register_task(...)`

| Parameter | Typ | Beschreibung |
|-----------|-----|--------------|
| `task_id` | `str` | Unique task ID |
| `task_type` | `str` | `SENSOR`, `ACTUATOR`, `MATH`, `MEASURE`, `CONTROL`, `GENERATOR` |
| `template` | `str` | Frontend template (for example, `tpl_generic_sensor`, `tpl_metric`) |
| `config` | `list[dict]` | Array of `configFields` according to the E-Lab schema (see `schema_reference.md`) |
| `unit` | `str` | Measurement unit |
| `sample_rate` | `int` | Sample rate in samples/s |
| `color` | `str` | Hex color (for example, `#3b82f6`) |
| `tags` | `list[str]` | Free-form tags for UI filtering |
| `ui_mode` | `str` | `generic` (default) or `custom` |
| `ui_url` | `str` | URL of the custom JavaScript plugin (only for `mode=custom`) |
| `ui_component_name` | `str` | Registered React component name of the custom plugin |
| `ui_integrity` | `str` | SRI hash of the custom plugin |
| `alias` | `str` | Optional display alias for the task |
| `decimals` | `int` | Number of decimal places rendered in the UI |
| `group_id` | `str` | Functional task group |
| `virtual` | `bool` | Marks the task as virtual |
| `group` | `str` | Task exclusivity group |
| `actions` | `list[dict]` | Declarative actuator actions |
| `decoder` | `dict` | Decoder definition for binary data |
| `ui_views` | `list[dict]` | Additional UI views according to the manifest schema |
| `ui_default_template` | `str` | Default template when multiple views are available |

With `ui_mode="custom"`, data processing, `publish`, `on_stream`, and Bridge
communication remain in the Python script. The JavaScript plugin only renders
the workbench presentation and must not be treated as a replacement for these
callbacks.

### `@node.on_config_update(task_id)`

A decorator for callbacks when UI parameters change. Signature: `(key: str, value: Any) -> None`

### `@node.on_stream(source_id)`

A decorator for incoming data chunks. Signature: `(data: np.ndarray) -> None`

### `node.publish(task_id, data)`

Publishes a NumPy array through shared memory to the dispatcher.

### `node.send_command(target_task_id, action, payload)`

Sends an actuator command to another task (for example, switching a relay).

### `node.fetch_history(session_id, source_id, start_time, end_time)`

Loads recorded session data as a NumPy array (for offline ML training).

---

## Tips and Best Practices

1. **Preserve filter state:** For chunk-based processing, always keep `zi`/`zf` (initial/final state) to avoid artifacts at chunk boundaries.
2. **No frontend code required:** When using `configFields` and existing templates, the workbench builds the UI automatically.
3. **Graceful shutdown:** `LocalNode` automatically registers signal handlers (SIGINT/SIGTERM) and releases shared memory.
4. **Measure latency:** For real-time control loops, measure effective latency with `time.perf_counter_ns()`. Target < 1 ms for the data plane and < 5 ms for the control plane.
