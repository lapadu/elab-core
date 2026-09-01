# Plugin Development Guide

This document describes how to add a new task / device plugin to the
E-Lab dispatcher and the workbench.

> Audience: Python developers (clients) and JavaScript developers
> (custom UI plugins). For a high-level project overview see
> [overview.md](overview.md) and [classes.md](classes.md).

## 1. Architecture in 30 seconds

```text
ESP32 / Python client  ──► Dispatcher (Python, gevent + Flask-SocketIO)  ──► Workbench (React)
        │                          │                                              │
        │  manifest                │  manifest forwarding                         │  Generic widgets
        │  data_stream             │  decoder pipeline                            │  Custom plugin (optional)
        ▼                          ▼                                              ▼
  ManifestBuilder           DecoderRegistry                               PluginRegistry
```

Three contracts matter:

1. **Manifest** — JSON describing what the device exposes. Validated
   against [`schemas/ManifestSchema.json`](../schemas/ManifestSchema.json)
   on the client side (best effort) and on the server side
   (`elab_server/manifest_builder.py`).
2. **Stream payload** — `data_stream` events carry decoded scalar
   samples or raw binary that the dispatcher decodes via a registered
   decoder.
3. **UI hint** — `task.ui` instructs the workbench how to render a
   widget: `generic`, `scope`, `spectrum`, or a custom URL.

## 2. Adding a Python client

A minimal client looks like this (see
[`elab_clients_core/python/clients/TempTestClient.py`](../elab_clients_core/python/clients/TempTestClient.py)
for a complete example):

```python
import socketio
from elab_server.manifest_builder import ManifestBuilder

sio = socketio.Client()

builder = ManifestBuilder(provider_id="my-temp-sensor", name="Bench Temperature")
builder.add_task(
    task_id="temp",
    name="Temperature",
    task_type="SENSOR",
    ui_mode="generic",
    config={"unit": "°C", "min": -20, "max": 120},
)

@sio.event
def connect():
    sio.emit("register_provider", builder.build())

sio.connect("http://localhost:5000")
sio.wait()
```

Stream samples back with `sio.emit("data_stream", {...})`. The payload
shape is documented in [`api.md`](api.md).

### Sending raw binary (high-rate sensors)

For high-rate streams (e.g. 100 kSps) emit a binary chunk and let the
dispatcher decode it. Add a decoder hint to the task:

```python
builder.add_task(
    ...,
    decoder={
        "type": "generic_binary",
        "parameters": {
            "dataType": "uint16",
            "endianness": "little",
            "zeroValue": 32768,
            "valueRange": 32768.0,
            "measurementRange": 5.0,
            # Optional: linearization lookup table
            "linearizationTable": [[0, 0.0], [65535, 5.0]],
        },
    },
)
```

The dispatcher rejects unknown decoder names at registration time
(see `_validate_decoder` in `manifest_builder.py`).

### 2.2 Enabling Trigger Support

If a task supports triggers (allowing users to set thresholds, modes like rising/falling edge, and channels on both desktop and mobile devices), it can declare support in the manifest. 

A task supports triggers if:
- It uses the standard time-domain scope template: `ui.defaultTemplate = "tpl_scope"` or `ui.template = "tpl_scope"`.
- OR it declares `"trigger"` in its task `capabilities` array (e.g., `capabilities=["measure", "trigger"]`).
- OR its config explicitly pre-defines a `trigger` configuration block (e.g., `config={"trigger": {"mode": "rising", "level": 0.0, "channelId": None}}`).

Once support is detected, the workbench automatically enables:
1. Drag-and-drop or touch-drag placement of trigger tasks onto the widget.
2. The trigger control panel in the workbench widget.
3. Click-to-assign / tap-to-assign channel shortcuts inside the trigger menu (especially useful on mobile/touch screens where drag-and-drop is not available).

## 3. Custom UI plugin (JavaScript)

If the generic widget is not enough, ship a small JS file with the
client and reference it from the manifest.

### 3.1 Write the plugin

A plugin is a single self-registering JS file. Example
([`elab_clients_core/python/assets/freq_counter_plugin.js`](../elab_clients_core/python/assets/freq_counter_plugin.js)):

```js
window.registerElabPlugin('MyWidget', (React, Icons) => {
  const { useState } = React;
  return ({ task, latest, send }) => {
    return (
      <div className="rounded p-2">
        <div className="text-sm">{task.name}</div>
        <div className="text-2xl">{latest?.value ?? '—'}</div>
      </div>
    );
  };
});
```

Available APIs in the second argument: React + a small subset of
`lucide-react` icons. The factory must return a React component.

### 3.2 Serve and reference it

Host the file on the client itself (most Python clients run a small
HTTP server for assets). Then point the manifest at it:

```python
from elab_clients_core.python.shared.plugin_security import compute_plugin_sri

PLUGIN_URL = "http://192.168.1.50:8080/freq_counter_plugin.js"
PLUGIN_INTEGRITY = compute_plugin_sri("assets/freq_counter_plugin.js")

builder.add_task(
    ...,
    ui_mode="custom",
    ui_url=PLUGIN_URL,
    ui_integrity=PLUGIN_INTEGRITY,  # SHA-256 SRI hash
)
```

### 3.3 Security model

Two independent guards prevent rogue plugin code from compromising a
workbench session:

| Guard | Where | What it does |
| --- | --- | --- |
| **SRI** (`ui.integrity`) | Browser (`script.integrity`) | Refuses to execute the file if the bytes do not match the published hash. Prevents MITM injection on the LAN. |
| **Origin allow-list** | Dispatcher (env + CLI) | Strips `ui.url` and `ui.integrity` for any host that is neither the provider's own IP nor in the allow-list. The widget falls back to `generic` mode. |

The origin allow-list can be configured two ways (both are merged):

**1. Environment variable** (`ELAB_PLUGIN_ORIGINS`)
```bash
export ELAB_PLUGIN_ORIGINS="http://192.168.1.50:8080,http://internal-cdn.lab:*"
python server.py
```

**2. CLI argument** (`--plugin-origins`; useful for systemd/process managers)
```bash
python server.py --plugin-origins "http://192.168.1.50:8080,http://internal-cdn.lab:*"
```

Both sources are merged at startup. Origins must be in format `scheme://host[:port]` or `scheme://host:*` (port wildcard).
If your plugins live on a Raspberry Pi or other single-board computer managed by a process manager (e.g. systemd),
edit the service's `ExecStart` or use `Environment=` directives to set origins without modifying source code or requiring a restart-heavy env-var change workflow.

For ESP32 clients (no horsepower for crypto), keep `ui_mode="generic"`.
The manifest-based generic widgets handle the vast majority of
sensor / actuator use cases.

> **Never load plugins from a third-party CDN.** Plugin code runs with
> the workbench's privileges and can issue dispatcher commands on
> behalf of the user.

## 4. Decoder plugins (server-side)

If your hardware encoding is not covered by `generic_binary`, register
a custom decoder in `elab_server/decoders.py`:

```python
@DecoderRegistry.register("my_protocol")
class MyDecoder(BaseDecoder):
    def decode(self, binary_data: bytes) -> list[float]:
        if not binary_data:
            return []
        # ... parse and return scalar values ...
```

Then reference it in the client's task manifest with
`decoder={"type": "my_protocol", "parameters": {...}}`.

Decoders **must not raise** on malformed input. Return `[]` and log a
warning instead. Tests live in `tests/test_decoders.py`.

## 5. Testing checklist

Before shipping a plugin:

- [ ] Manifest passes the schema (`schemas/ManifestSchema.json`).
- [ ] Decoder (if custom) handles `b""`, `None`, and misaligned
      payloads without raising.
- [ ] If you publish a custom UI plugin, the SRI hash is computed at
      startup (not hard-coded).
- [ ] The dispatcher logs no `Schema violation` warnings during
      registration.
- [ ] `pytest -q` and `npm test --prefix elab_workbench` are green.

## 6. Reference

- [api.md](api.md) — full Socket.IO event reference
- [classes.md](classes.md) — module map
- [schema_reference.md](schema_reference.md) — how schema
  validation is wired into both ends
- [overview.md](overview.md) — architecture and design choices
