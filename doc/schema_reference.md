# Manifest Schema & Integration

_Auto-generated from `schemas/ManifestSchema.json`. Do not edit manually._

Generated: 2026-07-13 08:01:05 UTC

To ensure consistency and stability in the distributed E-Lab system, manifests are validated by a central JSON schema.

The authoritative schema file is located at:
`schemas/ManifestSchema.json`

## Integration Architecture

1. Server as source: The Flask server serves the schema at `/schemas/ManifestSchema.json`.
2. Clients should download this schema at startup.
3. Clients should build manifests with `elab_server.manifest_builder.ManifestBuilder`.
4. Server re-validates manifests on `register_provider`.

## Client Implementation (Python)

Example:

```python
import json
import urllib.request
import urllib.error
import socket
from elab_server.manifest_builder import ManifestBuilder


def download_schema(dispatcher_url: str):
    """Download schema from dispatcher server."""
    schema_url = f"{dispatcher_url}/schemas/ManifestSchema.json"
    try:
        with urllib.request.urlopen(schema_url, timeout=5) as response:
            if response.status == 200:
                return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, socket.timeout):
        return None
    return None


# Assumption: dispatcher_url was already found via UDP discovery
schema = download_schema(dispatcher_url)

builder = ManifestBuilder(
    provider_id="my_device_01",
    name="My Awesome Device",
    schema_dict=schema,
)

builder.add_task(
    task_id="my_device_01_temp",
    name="Temperature",
    task_type="SENSOR",
    ui_mode="generic",
    ui_template="tpl_metric",
    color="#ef4444",
    tags=["temperature", "usb"],
    config={
        "unit": "°C",
        "range": [-20, 100],
        "accuracy": {
            "model": "percent_reading_plus_digits",
            "relativePctReading": 0.5,
            "digits": 2,
            "digitReference": "ui_lsd",
            "displayStep": 0.01,
            "confidenceK": 2.0,
        },
    },
)

DEVICE_MANIFEST = builder.build()
# sio.emit("register_provider", DEVICE_MANIFEST)
```

## Manifest Schema Reference

### Root Object

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `id` | `string` | required | Permanent, globally unique provider identifier. Must remain constant across restarts and reconnects – derived from hardware serial number, MAC address, or equivalent immutable source. |
| `name` | `string` | required | Human-readable name displayed in the UI (e.g., Frequency Counter RaspberryPi). |
| `category` | `string` | required | Provider category. HARDWARE for physical devices (incl. adapters), VIRTUAL_INTERNAL for built-in virtual sources, VIRTUAL_SCRIPT for script-based virtual sources. |
| `providerVersion` | `string` | optional | Provider implementation version. |
| `apiVersion` | `string` | optional | API version for compatibility checks. |
| `persistConfig` | `boolean` | optional | If true, the provider persists configuration (alias, color overrides) autonomously. This means the device behaves identically across different E-Lab instances. If false (default), the E-Lab dispatcher stores configuration in its SQLite DB on behalf of the provider. |
| `tasks` | `Task[]` | required | A list of Task objects this provider offers. Must contain at least one task. |

### Nested Objects

#### `Task` Object

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `id` | `string` | required | Permanent, unique task identifier. Must remain constant across restarts – like a hardware serial number or MAC-derived value. Used by E-Lab to track configuration (alias, color) persistently. |
| `name` | `string` | required | Display name for the task in the UI (e.g., Channel A (Frequency)). |
| `type` | `string` | required | Task type. Must be SENSOR, ACTUATOR, MATH, MEASURE, CONTROL, or GENERATOR. |
| `groupId` | `string` | optional | Groups tasks within a provider into a functional unit. The hardware supports only one task of a group at a time. |
| `color` | `string` | optional | Default hex color for this task (e.g. #ef4444). Acts as the initial visualization color for SENSOR, MATH, MEASURE, CONTROL, and GENERATOR tasks. Can be overridden at runtime by the user at source or sink level. Color changes at a sink propagate back to the nearest upstream source (but not beyond intermediate processing modules like MATH). |
| `virtual` | `boolean` | optional | True if the task is purely virtual and not based on real hardware. |
| `tags` | `string[]` | optional | Freeform tags for filtering in the UI (e.g. multimeter, temperature, usb). |
| `group` | `string` | optional | Task group for exclusivity. Tasks in the same group can be dispatched in parallel; tasks in different groups are mutually exclusive per provider. |
| `actions` | `object[]` | optional | Declarative list of special commands that the task provider supports. The UI renders action buttons only for declared actions. |
| `config` | `object` | optional | Task runtime configuration. Any model-level uncertainty should be declared in config.accuracy so UI and MATH tasks can propagate uncertainty consistently. |
| `decoder` | `object` | optional | Decoder converts transport/binary payload to engineering units. If linearizationTable is present, uncertainty transformation should use local derivative (segment slope), not a global range ratio. |
| `ui` | `object` | required | An object defining the UI representation (see below). |

#### `ui` Object

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `mode` | `string` | required | generic for standard widgets or custom for a URL-loaded UI. |
| `template` | `string` | conditional | Required for mode=generic. Name of the UI template to use (e.g., tpl_metric). |
| `url` | `string` | conditional | Required for mode=custom. URL to the custom UI JavaScript file. |
| `integrity` | `string` | conditional | Optional Subresource Integrity (SRI) hash for the remote plugin script. |
| `componentName` | `string` | conditional | Required for mode=custom. Name of the React component exported by the script. |
| `apiVersion` | `string` | optional | API version expected by the remote plugin. |
| `views` | `object[]` | optional | Array of alternative views for a widget. Each object contains id, label, icon, template. |
| `defaultTemplate` | `string` | optional | Only for mode=custom. Fallback template ID used for generic/template rendering. |

#### `config` Object

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `range` | `number[]` | optional | Value range for displays, e.g., [0, 100]. |
| `unit` | `string` | optional | Unit of measurement, e.g., Hz, °C, V. |
| `siUnit` | `string` | optional | SI unit, if different from unit. |
| `factor` | `number` | optional | Multiplication factor to convert from unit to siUnit. |
| `triggerMode` | `string` | optional | Optional trigger mode for signal/event based processing tasks. |
| `sampleRate` | `number` | optional | Sample rate in samples per second. Describes the resolution of a SENSOR stream. |
| `accuracy` | `AccuracyObject\|null` | optional | Structured measurement uncertainty model. Set to null to disable uncertainty metadata for this task. Server uses this object to derive payload uncertainty in decoded units. Prefer explicit models over a single percent number. |
| `medianGroupSize` | `number` | optional | Optional window/group size used by median-style processors. |
| `dmaBufferSamples` | `number` | optional | Optional DMA buffer size in samples for hardware-backed streams. |
| `noiseEnabled` | `boolean` | optional | Optional flag to enable/disable synthetic noise in generator tasks. |
| `accepts` | `string[]` | optional | Optional input capability hint for ACTUATOR tasks. Use values like scalar, array, values, stream to declare supported command payload shapes. |
| `maxRateHz` | `number` | optional | Optional upper bound for command delivery rate to this task (commands per second). |
| `singleSource` | `boolean` | optional | Optional flag that limits this task to one upstream input source. |
| `providerId` | `string` | optional | Optional provider reference used by virtual/system tasks. |
| `configFields` | `object[]` | optional | Definition of generic configuration UI elements (see below). |

#### `actions` Array Elements

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `id` | `string` | required | The command action string sent via cmd_control (e.g. START_RAW). |
| `label` | `string` | required | Human-readable action label shown as button tooltip/text in the UI. |
| `icon` | `string` | optional | Lucide icon name to display in the UI. |

##### `accuracy` Object

`accuracy.model` supports these standard models:

| Model | Purpose | Key Fields |
| --- | --- | --- |
| `percent_reading` | Relative Anteil vom Messwert | `relativePctReading` |
| `absolute` | Konstanter absoluter Fehler | `absoluteOffset` |
| `percent_reading_plus_absolute` | Kombination aus relativ + absolut | `relativePctReading`, `absoluteOffset` |
| `percent_reading_plus_digits` | DMM-artig: `% reading + digits` | `relativePctReading`, `digits`, `digitReference`, optional `displayStep`/`digitStep` |
| `adc_quantization_only` | Quantisierungsrauschen | Decoder/ADC-Kontext |
| `random_sigma` | Direkter statistischer Anteil | `randomSigma` |
| `combined` | Kombination mehrerer Modelle | `systematic`, `random` |

Shared fields:

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `model` | `string` | required | Use 'combined' to compose nested systematic/random models. Use 'percent_reading_plus_digits' for DMM-like specs. |
| `relativePctReading` | `number` | optional | Relative contribution in percent of \|measured value\|. |
| `absoluteOffset` | `number` | optional | Absolute contribution in measurement unit. |
| `digits` | `number` | optional | Count of display digits in a '% reading + digits' model. |
| `digitReference` | `string` | optional | ESP32/ADC note: adc_lsb may differ from UI least-significant digit. Choose explicitly. |
| `displayStep` | `number` | optional | Absolute step size of UI LSD when digitReference == ui_lsd. |
| `digitStep` | `number` | optional | Explicit absolute step size when digitReference == explicit_step. |
| `randomSigma` | `number` | optional | Random uncertainty as 1-sigma in measurement unit. |
| `confidenceK` | `number` | optional | Coverage factor for display bounds (for example k=2). |
| `systematic` | `AccuracyObject` | optional | Nested model for systematic contribution. |
| `random` | `AccuracyObject` | optional | Nested model for random contribution. |

#### `configFields` Array Elements

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `key` | `string` | required | The property key under which the value is stored and sent. |
| `label` | `string` | required | Display name of the configuration element. |
| `type` | `string` | required | UI element type: number, slider, select, toggle, datetime, text, button. |
| `value` | `object` | optional | Current value used to initialize the UI. |
| `min` | `number` | conditional | Minimum value (relevant for number and slider). |
| `max` | `number` | conditional | Maximum value (relevant for number and slider). |
| `step` | `number` | conditional | Step size (relevant for number and slider). |
| `unit` | `string` | optional | Unit label (for example Hz) displayed next to the field. |
| `default` | `object` | optional | Default value used when current value is missing. |
| `placeholder` | `string` | optional | Placeholder text for text input fields. |
| `buttonText` | `string` | optional | Label for button fields. Clicking triggers update_config with action=key. |
| `options` | `object[]` | conditional | Choices for type=select. Each element contains label and value. |

#### `decoder` Object

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `type` | `string` | optional | Name of the decoder to use (for example generic_binary). |
| `parameters` | `object` | optional | Decoder-specific parameters object. |

##### `decoder.parameters`

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `dataType` | `string` | optional | Binary data type (e.g., uint8, uint16, float32). |
| `endianness` | `string` | optional | Byte order for multi-byte numeric types: big or little. |
| `zeroValue` | `number` | optional | Raw zero/reference value used before scaling. |
| `valueRange` | `number` | optional | Raw numeric span used by scaling. |
| `measurementRange` | `number` | optional | Engineering-unit span after scaling. |
| `linearizationTable` | `number[][]` | optional | Piecewise-linear transfer table [x_raw_scaled, y_engineering]. For uncertainty mapping, use local dy/dx from the active segment. |

## Frontend Integration (TypeScript Types)

The type definitions for `Manifest` in the frontend are generated from `schemas/ManifestSchema.json`.
Do not edit `src/plugins/core/ManifestTypes.ts` manually.

Run after schema changes:

```bash
# Run in elab_workbench
npm run generate-types
```
