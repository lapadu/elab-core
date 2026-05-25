# Local API Bridge – Benutzerhandbuch

Die **Local API Bridge** ermöglicht es externen Python-Skripten, sich nahtlos in das E-Lab-Ökosystem einzuklinken. Über einen Hybrid-IPC-Ansatz (ZeroMQ + Shared Memory) können Skripte hochfrequente Datenströme verarbeiten, Steuersignale senden und native UI-Widgets in der React-Workbench bereitstellen – ohne eigenen Frontend-Code.

## Voraussetzungen

Im Projekt-Root installieren (empfohlen, editable für Entwicklung):

```bash
pip install -e .
```

Danach sind `elab_api` und `elab_bridge` überall in derselben Python-Umgebung importierbar.

Alternative ohne editable Install:

```bash
pip install .
```

Zusätzliche direkte Abhängigkeiten (falls nur Teilmodule installiert werden):

```bash
pip install pyzmq numpy
```

Für DSP-Anwendungen zusätzlich:

```bash
pip install scipy
```

## Architektur

```
Externes Skript  ←─ ZMQ + SHM ─→  Bridge Daemon  ←─ Socket.IO ─→  Dispatcher
  (elab_api)                        (elab_bridge)                   (server.py)
```

| Ebene | Transport | Zweck |
|-------|-----------|-------|
| **Control Plane** | ZeroMQ (REQ/REP, Port 5580) | Registrierung, Config-Updates, Aktorbefehle |
| **Notification** | ZeroMQ (PUB/SUB, Port 5581) | Async-Events vom Dispatcher → Skript |
| **Data Plane** | Shared Memory (Ring-Buffer) | Zero-Copy NumPy-Streaming (≤ 1 ms Latenz) |

## Quickstart

### 1. Bridge Daemon starten

```bash
python -m elab_bridge.bridge_daemon --dispatcher-url http://127.0.0.1:5000
```

Oder über den Console-Script-Entry-Point (nach `pip install -e .`):

```bash
elab-bridge-daemon --dispatcher-url http://127.0.0.1:5000
```

### 2. Externes Skript ausführen

```python
from elab_api import LocalNode

node = LocalNode(name="My Script")
node.register_task(task_id="output", task_type="SENSOR", template="tpl_generic_sensor")
node.run()
```

---

## Vollständiges Beispiel: FIR-Filter Node

Das folgende Skript implementiert einen konfigurierbaren FIR-Tiefpassfilter. Es abonniert einen Rohdatenstrom (z. B. von einem ESP32-Voltmeter), wendet den Filter an und publiziert das gefilterte Signal als neuen virtuellen Sensor in der Workbench.

```python
"""FIR-Filter Node für E-Lab.

Abonniert einen Rohdatenstrom, wendet einen konfigurierbaren FIR-Filter an
und publiziert das gefilterte Signal als neuen virtuellen Sensor.
"""
import numpy as np
from scipy.signal import firwin, lfilter
from elab_api import LocalNode

# --- Konfiguration ---
SOURCE_TASK = "esp32_voltmeter_raw"   # Rohdaten-Quelle (Task-ID im Dispatcher)
OUTPUT_TASK = "fir_filtered_signal"
INITIAL_CUTOFF = 100       # Hz
INITIAL_ORDER = 51         # Anzahl Koeffizienten
SAMPLE_RATE = 10000        # Hz (muss zur Quelle passen)

# --- Filter-State ---
fir_coeffs = firwin(INITIAL_ORDER, INITIAL_CUTOFF, fs=SAMPLE_RATE)
filter_state = np.zeros(INITIAL_ORDER - 1)


def rebuild_filter(order: int, cutoff: float) -> None:
    """Berechnet die FIR-Koeffizienten neu."""
    global fir_coeffs, filter_state
    fir_coeffs = firwin(order, cutoff, fs=SAMPLE_RATE)
    filter_state = np.zeros(order - 1)


# --- Node Setup ---
node = LocalNode(name="FIR Lowpass Filter")

# Task-Registrierung mit nativen E-Lab configFields (kein Frontend-Code nötig!)
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
            "label": "Cutoff-Frequenz",
            "type": "slider",
            "value": INITIAL_CUTOFF,
            "min": 10,
            "max": SAMPLE_RATE // 2 - 1,
            "step": 10,
            "unit": "Hz",
        },
        {
            "key": "filter_order",
            "label": "Filter-Ordnung",
            "type": "number",
            "value": INITIAL_ORDER,
            "min": 5,
            "max": 255,
            "step": 2,
        },
        {
            "key": "filter_type",
            "label": "Fenster-Funktion",
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
            "label": "Filter aktiv",
            "type": "toggle",
            "value": True,
        },
    ],
)


# --- Callbacks ---
@node.on_config_update(OUTPUT_TASK)
def on_config_changed(key: str, value):
    """Wird aufgerufen wenn der Benutzer einen Parameter in der UI ändert."""
    global fir_coeffs, filter_state, INITIAL_CUTOFF, INITIAL_ORDER

    if key == "cutoff_freq":
        INITIAL_CUTOFF = int(value)
        rebuild_filter(INITIAL_ORDER, INITIAL_CUTOFF)
        print(f"✔ Cutoff geändert: {INITIAL_CUTOFF} Hz")

    elif key == "filter_order":
        INITIAL_ORDER = int(value)
        rebuild_filter(INITIAL_ORDER, INITIAL_CUTOFF)
        print(f"✔ Ordnung geändert: {INITIAL_ORDER} Taps")

    elif key == "filter_type":
        fir_coeffs = firwin(INITIAL_ORDER, INITIAL_CUTOFF,
                            fs=SAMPLE_RATE, window=str(value))
        filter_state = np.zeros(INITIAL_ORDER - 1)
        print(f"✔ Fensterfunktion geändert: {value}")

    elif key == "enabled":
        print(f"✔ Filter {'aktiviert' if value else 'deaktiviert'}")


@node.on_stream(SOURCE_TASK)
def process_chunk(data: np.ndarray):
    """Verarbeitet eingehende Rohdaten-Chunks (Zero-Copy via Shared Memory)."""
    global filter_state

    # FIR-Filter anwenden (mit State für nahtlose Chunk-Übergänge)
    filtered, filter_state = lfilter(fir_coeffs, 1.0, data, zi=filter_state)

    # Gefiltertes Signal publizieren → erscheint als neuer Sensor in der UI
    node.publish(OUTPUT_TASK, filtered.astype(np.float32))


# --- Start ---
if __name__ == "__main__":
    print(f"FIR-Filter Node gestartet")
    print(f"  Quelle:  {SOURCE_TASK}")
    print(f"  Ausgang: {OUTPUT_TASK}")
    print(f"  Cutoff:  {INITIAL_CUTOFF} Hz / Ordnung: {INITIAL_ORDER}")
    node.run()
```

### Ausführung

```bash
# 1. E-Lab Dispatcher starten
python server.py

# 2. Bridge Daemon starten
python -m elab_bridge.bridge_daemon

# 3. FIR-Filter Skript starten
python elab_clients_core/python/api/fir_filter_node.py
```

Nach dem Start erscheint der Task `fir_filtered_signal` automatisch in der Workbench. Der Benutzer kann das Widget auf das Grid ziehen und die Filter-Parameter (Cutoff, Ordnung, Fenster) live über die generierten Slider/Selects anpassen.

---

## API-Referenz

### `LocalNode(name, bridge_host, control_port, notify_port)`

| Parameter | Default | Beschreibung |
|-----------|---------|--------------|
| `name` | – | Anzeigename in der UI |
| `bridge_host` | `"127.0.0.1"` | Bridge-Daemon Host |
| `control_port` | `5580` | ZMQ REQ/REP Port |
| `notify_port` | `5581` | ZMQ PUB/SUB Port |

### `node.register_task(...)`

| Parameter | Typ | Beschreibung |
|-----------|-----|--------------|
| `task_id` | `str` | Eindeutige Task-ID |
| `task_type` | `str` | `SENSOR`, `ACTUATOR`, `MATH`, `MEASURE`, `CONTROL`, `GENERATOR` |
| `template` | `str` | Frontend-Template (z. B. `tpl_generic_sensor`, `tpl_metric`) |
| `config` | `list[dict]` | Array von `configFields` gemäß E-Lab Schema (→ `schema_reference.md`) |
| `unit` | `str` | Maßeinheit |
| `sample_rate` | `int` | Abtastrate in Samples/s |
| `color` | `str` | Hex-Farbe (z. B. `#3b82f6`) |
| `tags` | `list[str]` | Freeform-Tags für UI-Filterung |
| `ui_mode` | `str` | `generic` (Standard) oder `custom` |
| `ui_url` | `str` | URL zu Custom-JS-Plugin (nur `mode=custom`) |

### `@node.on_config_update(task_id)`

Decorator für Callbacks bei UI-Parameteränderungen. Signatur: `(key: str, value: Any) -> None`

### `@node.on_stream(source_id)`

Decorator für eingehende Datenchunks. Signatur: `(data: np.ndarray) -> None`

### `node.publish(task_id, data)`

Publiziert ein NumPy-Array über Shared Memory an den Dispatcher.

### `node.send_command(target_task_id, action, payload)`

Sendet einen Aktorbefehl an einen anderen Task (z. B. Relais schalten).

### `node.fetch_history(session_id, source_id, start_time, end_time)`

Lädt aufgezeichnete Session-Daten als NumPy-Array (für Offline-ML-Training).

---

## Tipps & Best Practices

1. **Filter-State beibehalten:** Bei chunk-weiser Verarbeitung immer `zi`/`zf` (Initial-/Finalzustand) nutzen, um Artefakte an Chunk-Grenzen zu vermeiden.
2. **Kein Frontend-Code nötig:** Durch Nutzung der `configFields` und bestehender Templates baut die Workbench die UI automatisch.
3. **Graceful Shutdown:** `LocalNode` registriert automatisch Signal-Handler (SIGINT/SIGTERM) und räumt Shared Memory auf.
4. **Latenz testen:** Für Echtzeit-Regelschleifen die effektive Latenz mit `time.perf_counter_ns()` messen. Ziel: < 1 ms Data-Plane, < 5 ms Control-Plane.
