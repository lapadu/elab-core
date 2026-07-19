"""Generate doc/schema_reference.md from schemas/ManifestSchema.json.

This script keeps schema reference tables in sync with the authoritative
JSON schema. Intro text and Python examples are intentionally hard-coded
so project-specific guidance stays readable.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = REPO_ROOT / "schemas" / "ManifestSchema.json"
DOC_PATH = REPO_ROOT / "doc" / "schema_reference.md"


_REF_LABELS: dict[str, str] = {
    "task": "Task",
    "accuracyObject": "AccuracyObject",
}


_DESC_FALLBACKS: dict[str, str] = {
    "root.name": "Human-readable name displayed in the UI (e.g., Frequency Counter RaspberryPi).",
    "root.tasks": "A list of Task objects this provider offers. Must contain at least one task.",
    "task.name": "Display name for the task in the UI (e.g., Channel A (Frequency)).",
    "task.type": "Task type. Must be SENSOR, ACTUATOR, MATH, MEASURE, CONTROL, or GENERATOR.",
    "task.virtual": "True if the task is purely virtual and not based on real hardware.",
    "task.config": "An object with configuration parameters for the task (see below).",
    "task.decoder": "Configuration for server-side binary data decoding (see below).",
    "task.ui": "An object defining the UI representation (see below).",
    "ui.mode": "generic for standard widgets or custom for a URL-loaded UI.",
    "ui.template": "Required for mode=generic. Name of the UI template to use (e.g., tpl_metric).",
    "ui.url": "Required for mode=custom. URL to the custom UI JavaScript file.",
    "ui.componentName": "Required for mode=custom. Name of the React component exported by the script.",
    "ui.views": "Array of alternative views for a widget. Each object contains id, label, icon, template.",
    "ui.defaultTemplate": "Only for mode=custom. Fallback template ID used for generic/template rendering.",
    "config.range": "Value range for displays, e.g., [0, 100].",
    "config.unit": "Unit of measurement, e.g., Hz, °C, V.",
    "config.siUnit": "SI unit, if different from unit.",
    "config.triggerMode": "Optional trigger mode for signal/event based processing tasks.",
    "config.medianGroupSize": "Optional window/group size used by median-style processors.",
    "config.dmaBufferSamples": "Optional DMA buffer size in samples for hardware-backed streams.",
    "config.noiseEnabled": "Optional flag to enable/disable synthetic noise in generator tasks.",
    "config.accepts": "Optional input capability hint for ACTUATOR tasks. Use values like scalar, array, values, stream to declare supported command payload shapes. Example: [\"scalar\"] for constrained devices that only consume single values.",
    "config.maxRateHz": "Optional upper bound for command delivery rate to this task (commands per second). The dispatcher may throttle source→actuator forwarding to this rate to protect resource-constrained clients (for example ESP32).",
    "config.singleSource": "Optional flag that limits this task to one upstream input source.",
    "config.providerId": "Optional provider reference used by virtual/system tasks.",
    "config.configFields": "Definition of generic configuration UI elements (see below).",
    "configFields.key": "The property key under which the value is stored and sent.",
    "configFields.label": "Display name of the configuration element.",
    "configFields.type": "UI element type: number, slider, select, toggle, datetime, text, button.",
    "configFields.min": "Minimum value (relevant for number and slider).",
    "configFields.max": "Maximum value (relevant for number and slider).",
    "configFields.step": "Step size (relevant for number and slider).",
    "configFields.unit": "Unit label (e.g., Hz) for display.",
    "configFields.default": "Default value used when the current value is not set.",
    "configFields.options": "Choices for type=select. Each element has label and value.",
    "configFields.value": "Current value used to initialize the UI.",
    "configFields.placeholder": "Placeholder text for type=text.",
    "configFields.buttonText": "Label for type=button. Triggers an update action with action=key.",
    "actions.label": "Human-readable action label shown as button tooltip/text in the UI.",
    "decoder.type": "Name of the decoder to use (for example generic_binary).",
    "decoder.parameters": "Decoder-specific parameters object.",
    "decoder.parameters.dataType": "Binary data type (e.g., uint8, uint16, float32).",
    "decoder.parameters.endianness": "Byte order for multi-byte numeric types: big or little.",
    "decoder.parameters.zeroValue": "Raw zero/reference value used before scaling.",
    "decoder.parameters.valueRange": "Raw numeric span used by scaling.",
    "decoder.parameters.measurementRange": "Engineering-unit span after scaling.",
}


def _load_schema(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _ref_name(ref: str) -> str:
    raw = ref.rsplit("/", 1)[-1]
    return _REF_LABELS.get(raw, raw)


def _type_text(node: dict[str, Any]) -> str:
    if "$ref" in node:
        return _ref_name(str(node["$ref"]))

    for union_key in ("anyOf", "oneOf", "allOf"):
        parts = node.get(union_key)
        if isinstance(parts, list) and parts:
            type_parts: list[str] = []
            for part in parts:
                if isinstance(part, dict):
                    type_parts.append(_type_text(part))
            dedup = []
            for p in type_parts:
                if p not in dedup:
                    dedup.append(p)
            if dedup:
                return "|".join(dedup)

    node_type = node.get("type")
    if isinstance(node_type, list):
        return "|".join(str(t) for t in node_type)
    if isinstance(node_type, str):
        if node_type == "array":
            items = node.get("items")
            if isinstance(items, dict):
                return f"{_type_text(items)}[]"
            return "array"
        return node_type

    enum_vals = node.get("enum")
    if isinstance(enum_vals, list) and enum_vals:
        return "enum"

    return "object"


def _required_text(name: str, required: set[str], conditional: set[str] | None = None) -> str:
    if conditional and name in conditional:
        return "conditional"
    return "required" if name in required else "optional"


def _description_text(node: dict[str, Any], fallback_key: str = "") -> str:
    desc = str(node.get("description", "")).strip()
    comment = str(node.get("$comment", "")).strip()
    fallback = _DESC_FALLBACKS.get(fallback_key, "")
    if desc and comment:
        return f"{desc} {comment}"
    if desc:
        return desc
    if comment:
        return comment
    if fallback:
        return fallback
    return "-"


def _escape_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ").strip()


def _table(headers: list[str], rows: list[list[str]]) -> list[str]:
    head = "| " + " | ".join(headers) + " |"
    sep = "| " + " | ".join("---" for _ in headers) + " |"
    out = [head, sep]
    for row in rows:
        out.append("| " + " | ".join(_escape_cell(c) for c in row) + " |")
    return out


def _rows_for_properties(
    properties: dict[str, Any],
    required: set[str],
    conditional: set[str] | None = None,
    context: str = "",
) -> list[list[str]]:
    rows: list[list[str]] = []
    for key, node_any in properties.items():
        node = node_any if isinstance(node_any, dict) else {}
        rows.append(
            [
                f"`{key}`",
                f"`{_type_text(node)}`",
                _required_text(key, required, conditional),
                _description_text(node, f"{context}.{key}" if context else key),
            ]
        )
    return rows


def _python_example_block() -> str:
    return """```python
import json
import urllib.request
import urllib.error
import socket
from elab_server.manifest_builder import ManifestBuilder


def download_schema(dispatcher_url: str):
    \"\"\"Download schema from dispatcher server.\"\"\"
    schema_url = f\"{dispatcher_url}/schemas/ManifestSchema.json\"
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
"""


def _model_rows(models: list[str]) -> list[list[str]]:
    explanations = {
        "percent_reading": ("Relative Anteil vom Messwert", "`relativePctReading`"),
        "absolute": ("Konstanter absoluter Fehler", "`absoluteOffset`"),
        "percent_reading_plus_absolute": (
            "Kombination aus relativ + absolut",
            "`relativePctReading`, `absoluteOffset`",
        ),
        "percent_reading_plus_digits": (
            "DMM-artig: `% reading + digits`",
            "`relativePctReading`, `digits`, `digitReference`, optional `displayStep`/`digitStep`",
        ),
        "adc_quantization_only": ("Quantisierungsrauschen", "Decoder/ADC-Kontext"),
        "random_sigma": ("Direkter statistischer Anteil", "`randomSigma`"),
        "combined": ("Kombination mehrerer Modelle", "`systematic`, `random`"),
    }
    rows: list[list[str]] = []
    for model in models:
        desc, fields = explanations.get(model, ("-", "-"))
        rows.append([f"`{model}`", desc, fields])
    return rows


def generate() -> str:
    schema = _load_schema(SCHEMA_PATH)
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    defs = schema.get("definitions", {}) if isinstance(schema.get("definitions"), dict) else {}
    task_def = defs.get("task", {}) if isinstance(defs.get("task"), dict) else {}

    root_props = schema.get("properties", {}) if isinstance(schema.get("properties"), dict) else {}
    root_required = set(schema.get("required", [])) if isinstance(schema.get("required"), list) else set()

    task_props = task_def.get("properties", {}) if isinstance(task_def.get("properties"), dict) else {}
    task_required = set(task_def.get("required", [])) if isinstance(task_def.get("required"), list) else set()

    ui_def = task_props.get("ui", {}) if isinstance(task_props.get("ui"), dict) else {}
    ui_props = ui_def.get("properties", {}) if isinstance(ui_def.get("properties"), dict) else {}
    ui_required = set(ui_def.get("required", [])) if isinstance(ui_def.get("required"), list) else set()

    config_def = task_props.get("config", {}) if isinstance(task_props.get("config"), dict) else {}
    config_props = config_def.get("properties", {}) if isinstance(config_def.get("properties"), dict) else {}

    cfg_fields = config_props.get("configFields", {}) if isinstance(config_props.get("configFields"), dict) else {}
    cfg_item = cfg_fields.get("items", {}) if isinstance(cfg_fields.get("items"), dict) else {}
    cfg_props = cfg_item.get("properties", {}) if isinstance(cfg_item.get("properties"), dict) else {}
    cfg_required = set(cfg_item.get("required", [])) if isinstance(cfg_item.get("required"), list) else set()

    actions_def = task_props.get("actions", {}) if isinstance(task_props.get("actions"), dict) else {}
    actions_item = actions_def.get("items", {}) if isinstance(actions_def.get("items"), dict) else {}
    actions_props = actions_item.get("properties", {}) if isinstance(actions_item.get("properties"), dict) else {}
    actions_required = set(actions_item.get("required", [])) if isinstance(actions_item.get("required"), list) else set()

    dec_def = task_props.get("decoder", {}) if isinstance(task_props.get("decoder"), dict) else {}
    dec_props = dec_def.get("properties", {}) if isinstance(dec_def.get("properties"), dict) else {}
    dec_required = set(dec_def.get("required", [])) if isinstance(dec_def.get("required"), list) else set()

    dec_params = dec_props.get("parameters", {}) if isinstance(dec_props.get("parameters"), dict) else {}
    dec_param_props = dec_params.get("properties", {}) if isinstance(dec_params.get("properties"), dict) else {}

    acc_def = defs.get("accuracyObject", {}) if isinstance(defs.get("accuracyObject"), dict) else {}
    acc_props = acc_def.get("properties", {}) if isinstance(acc_def.get("properties"), dict) else {}
    acc_required = set(acc_def.get("required", [])) if isinstance(acc_def.get("required"), list) else set()
    acc_model_node = acc_props.get("model", {}) if isinstance(acc_props.get("model"), dict) else {}
    acc_models = [str(m) for m in acc_model_node.get("enum", [])] if isinstance(acc_model_node.get("enum"), list) else []

    lines: list[str] = [
        "# Manifest Schema & Integration",
        "",
        "_Auto-generated from `schemas/ManifestSchema.json`. Do not edit manually._",
        "",
        f"Generated: {generated}",
        "",
        "To ensure consistency and stability in the distributed E-Lab system, manifests are validated by a central JSON schema.",
        "",
        "The authoritative schema file is located at:",
        "`schemas/ManifestSchema.json`",
        "",
        "## Integration Architecture",
        "",
        "1. Server as source: The Flask server serves the schema at `/schemas/ManifestSchema.json`.",
        "2. Clients should download this schema at startup.",
        "3. Clients should build manifests with `elab_server.manifest_builder.ManifestBuilder`.",
        "4. Server re-validates manifests on `register_provider`.",
        "",
        "## Client Implementation (Python)",
        "",
        "Example:",
        "",
    ]
    lines.extend(_python_example_block().splitlines())

    lines.extend([
        "",
        "## Manifest Schema Reference",
        "",
        "### Root Object",
        "",
    ])
    lines.extend(_table(["Field", "Type", "Required", "Description"], _rows_for_properties(root_props, root_required, context="root")))

    lines.extend([
        "",
        "### Nested Objects",
        "",
        "#### `Task` Object",
        "",
    ])
    lines.extend(_table(["Field", "Type", "Required", "Description"], _rows_for_properties(task_props, task_required, context="task")))

    lines.extend([
        "",
        "#### `ui` Object",
        "",
    ])
    ui_conditional = {"template", "url", "integrity", "componentName"}
    lines.extend(_table(["Field", "Type", "Required", "Description"], _rows_for_properties(ui_props, ui_required, ui_conditional, context="ui")))

    lines.extend([
        "",
        "#### `config` Object",
        "",
    ])
    lines.extend(_table(["Field", "Type", "Required", "Description"], _rows_for_properties(config_props, set(), context="config")))

    lines.extend([
        "",
        "#### `actions` Array Elements",
        "",
    ])
    lines.extend(_table(["Field", "Type", "Required", "Description"], _rows_for_properties(actions_props, actions_required, context="actions")))

    lines.extend([
        "",
        "##### `accuracy` Object",
        "",
        "`accuracy.model` supports these standard models:",
        "",
    ])
    lines.extend(_table(["Model", "Purpose", "Key Fields"], _model_rows(acc_models)))

    lines.extend([
        "",
        "Shared fields:",
        "",
    ])
    lines.extend(_table(["Field", "Type", "Required", "Description"], _rows_for_properties(acc_props, acc_required, context="accuracy")))

    lines.extend([
        "",
        "#### `configFields` Array Elements",
        "",
    ])
    cfg_conditional = {"min", "max", "step", "options"}
    lines.extend(_table(["Field", "Type", "Required", "Description"], _rows_for_properties(cfg_props, cfg_required, cfg_conditional, context="configFields")))

    lines.extend([
        "",
        "#### `decoder` Object",
        "",
    ])
    lines.extend(_table(["Field", "Type", "Required", "Description"], _rows_for_properties(dec_props, dec_required, context="decoder")))

    lines.extend([
        "",
        "##### `decoder.parameters`",
        "",
    ])
    lines.extend(_table(["Field", "Type", "Required", "Description"], _rows_for_properties(dec_param_props, set(), context="decoder.parameters")))

    lines.extend([
        "",
        "## Frontend Integration (TypeScript Types)",
        "",
        "The type definitions for `Manifest` in the frontend are generated from `schemas/ManifestSchema.json`.",
        "Do not edit `src/plugins/core/ManifestTypes.ts` manually.",
        "",
        "Run after schema changes:",
        "",
        "```bash",
        "# Run in elab_workbench",
        "npm run generate-types",
        "```",
    ])

    return "\n".join(lines) + "\n"


def main() -> None:
    output = generate()
    DOC_PATH.write_text(output, encoding="utf-8")
    print(f"Generated {DOC_PATH}")


if __name__ == "__main__":
    main()
