# E-Lab API Documentation

This document describes the API for the E-Lab system, including REST endpoints and Socket.IO events.

## 1. REST API Endpoints

The Dispatcher server provides a few standard REST endpoints.

### `GET /api/health`

Returns the health status of the server.
**Response:**

```json
{
  "status": "online",
  "version": "x.y.z",
  "providers": 1,
  "clients": 2,
  "recording": false,
  "session_id": null,
  "uptime": 1690000000.123
}
```

### `GET /api/providers`

Returns the list of currently available providers.
**Response:**

```json
{
  "providers": [
    {
      "id": "esp32_voltmeter_01",
      "name": "Voltmeter",
      "tasks": [ ... ]
    }
  ]
}
```

### `GET /schemas/ManifestSchema.json`

Returns the JSON schema used to validate hardware provider manifests.

---

## 2. Socket.IO Events (Client -> Server)

Hardware providers and UI clients communicate with the Dispatcher via Socket.IO.

### `register_provider`

Registers a hardware provider and announces its tasks.

- **Payload:** `dict` (The Provider Manifest matching `ManifestSchema.json`)
  - Optional field `auto_approve_token` (string): one-shot token from
    `ELAB_AUTO_APPROVE_TOKEN` env var. Trusted local scripts spawned by
    the `ProcessManager` carry this automatically.
- **Server Action:** Validates the manifest, sanitizes plugin URLs against
  the allow-list, computes `manifest_hash` and looks up the device
  credential. Unknown or changed devices are quarantined.
- **Emits Back (Pairing flow — see [`security.md`](security.md)):**
  - `registration_approved` `{deviceId, secret, manifestHash}` — pairing
    complete, secret shipped exactly once.
  - `registration_pending` `{deviceId, manifestHash}` — operator approval
    required in the Workbench "Registrierung" section.
  - `registration_revoked` `{deviceId, reason?}` — credential withdrawn.
  - `provider_registered` (to UI clients) on approval, or
    `registration_error` on invalid manifest.

### `register_client`

Registers a UI client.

- **Payload:** `{ "type": "string" }`
- **Server Action:** Joins the client to the `ui_clients` room and sends the current system state.
- **Emits Back:** `available_providers`, `available_scripts`, and conditionally `active_tasks_snapshot` and `replay_status`.

### `data_stream` — Hardware Upload

Used by hardware providers to push new measurement data.

> **Authentication required (default).** Every `data_stream` packet MUST
> carry a signed `auth` block — see [`security.md`](security.md) for the
> exact format. Unsigned packets are silently dropped. To temporarily
> disable enforcement (test / migration), set `ELAB_REQUIRE_AUTH=0` on
> the server.
>
> ```json
> "auth": { "sig": "<hmac-sha256 hex>", "ts": 1735052819.123456 }
> ```

- **Payload (simple scalar):**

  ```json
  {
    "sourceId": "task_id_string",
    "value": 123.45,
    "timestamp": 1690000000123,
    "uncertainty": {
      "domain": "decoded",
      "model": "combined",
      "systematicAbs": 0.05,
      "randomSigma": 0.02,
      "confidenceK": 2.0
    }
  }
  ```

- **Payload (binary, alternative formats):**

  ```json
  {
    "sourceId": "task_id_string",
    "raw_bytes": [0, 128, 255],
    "timestamp": 1690000000123
  }
  ```

  Binary data can also be sent as `binary_payload` (raw bytes) or `binary_payload_b64` (base64-encoded string). The server will decode it through the configured decoder pipeline.

- **Payload (linear distribution / high-rate):**

  ```json
  {
    "sourceId": "task_id_string",
    "values": [1.0, 1.1, 1.2],
    "distribution": "linear",
    "startTime": 100,
    "endTime": 200,
    "uncertainty": {
      "domain": "decoded",
      "model": "combined",
      "systematicAbs": 0.05,
      "randomSigma": 0.02,
      "confidenceK": 2.0
    }
  }
  ```

- **`uncertainty` (optional):**
  - `domain`: `decoded` or `raw` (raw is mapped by the server decoder when possible)
  - `model`: typically `combined`
  - `systematicAbs`: absolute systematic bound in the payload unit
  - `randomSigma`: 1-sigma random uncertainty in the payload unit
  - `confidenceK`: optional coverage factor used for display

- **Server Action:** Normalizes timestamps, applies decoder if configured, buffers the data if recording is active, and immediately broadcasts it to all UI clients.

### `task_assigned`

Sent by UI when a task is dropped into a grid slot.

- **Payload:** `{ "slot": 0, "taskId": "esp32_voltmeter_01_ch1" }`
- **Server Action:** Checks group exclusivity, tracks the assigned task for recording context.
- **Emits Back:** `task_rejected` if the group exclusivity rule is violated.

### `task_unassigned`

Sent by UI when a task is removed from a grid slot.

- **Payload:** `{ "slot": 0 }`

### `cmd_control`

Used by UI to send a control command (e.g. settings change) to a specific hardware provider.

- **Payload:**

  ```json
  {
    "provider_id": "prov_esp32_voltmeter_01",
    "action": "update_config",
    "payload": { "range": 10 }
  }
  ```

- **Server Action:** Forwards the command to the specific provider's Socket.IO session via `execute_command`.

### `provider_meta_changed`

Used when a provider updates its own metadata (like display name or color).

- **Payload:**

  ```json
  {
    "task_id": "esp32_voltmeter_01_ch1",
    "changes": { "color": "#ff0000" }
  }
  ```

- **Server Action:** Updates state and broadcasts the change to all UI clients.

### Provider Pairing (UI -> Server)

See [`security.md`](security.md) for the full Trust-on-First-Use model.

- `get_pending_devices` — request the current pending list. Server
  replies with `pending_devices` (also broadcast to all UI clients on
  state changes).
- `approve_pending_device` — payload `{ "deviceId": "...", "manifestHash": "..." }`.
  Approves a pending provider; server hands the secret to the device via
  `registration_approved` and starts accepting its `data_stream`.
- `revoke_device` — payload `{ "deviceId": "..." }`. Disconnects the
  device and emits `registration_revoked`. Future reconnects re-enter
  the pending state.
- `delete_device_credential` — payload `{ "deviceId": "..." }`. Wipes
  the credential row entirely (admin / cleanup).

### Session & Recording Management

- `session_start` - Starts recording a new session. Payload: `{ "session_id": "Session Name" }`. Emits `session_start_result`.
- `session_stop` - Stops the active recording session. Emits `session_stop_result`.
- `get_sessions` - Retrieves a list of available recorded sessions. Emits `session_list` back.
- `delete_session` - Deletes a recorded session. Payload: `{ "session_id": "Session Name" }`
- `replay_load` - Loads a session for playback. Payload: `{ "session_id": "Session Name" }`. Emits `replay_loaded`.
- `replay_action` - Controls replay (play, pause, stop, seek, speed, unload). Payload: `{ "action": "play|pause|stop|seek|speed|unload", "value": ... }`
- `get_recorded_providers` - Retrieves the original manifest configuration for a recorded session. Payload: `{ "session_id": "Session Name" }`. Emits `recorded_providers`.

### Script Management

- `get_available_scripts` - Scans for available simulated Python clients. Emits `available_scripts`.
- `start_client_script` - Starts a Python script. Payload: `{ "filename": "FrequenceCounterClient.py" }`
- `stop_client_script` - Stops a Python script. Payload: `{ "filename": "FrequenceCounterClient.py" }`

---

## 3. Socket.IO Events (Server -> Client)

### `connection_established`

Emitted to every newly connected Socket.IO client immediately on connection.

- **Payload:**

  ```json
  {
    "client_id": "socket_session_id",
    "server_version": "x.y.z",
    "timestamp": 1690000000.123,
    "session_active": false,
    "session_id": null
  }
  ```

### `available_providers`

Broadcasted to UI clients when a provider connects, disconnects, or updates its state.

- **Payload:** `{ "providers": [...], "timestamp": ... }` — Array of active provider manifests.

### `provider_registered`

Broadcasted to UI clients when a new provider successfully registers.

- **Payload:** `{ "provider": { ... } }` — The registered manifest.

### `provider_offline`

Broadcasted to UI clients when a provider disconnects.

- **Payload:** `{ "provider_id": "esp32_voltmeter_01", "reason": "disconnect", "timestamp": ... }`

### `data_stream` — Server Broadcast

Broadcasted to UI clients with new live or replayed data.

### `execute_command`

Sent directly to a specific Hardware Provider to apply a configuration change.

- **Payload:** `{ "action": "update_config", "payload": { ... } }`

### `session_status`

Broadcasted when recording starts/stops.

- **Payload:** `{ "recording": boolean, "sessionId": string|null }`

### `replay_status` / `replay_progress`

Broadcasted during session playback to sync the UI slider and play/pause button.

### `active_tasks_snapshot`

Sent to a newly registered UI client with the current slot assignments.

- **Payload:** `{ "slots": { "0": "task_id_1", "1": "task_id_2" } }`

### `task_rejected`

Sent back to the requesting UI client when a task assignment violates group exclusivity.

- **Payload:** `{ "taskId": "...", "slot": 0, "reason": "..." }`

### `task_config_changed`

Broadcasted to UI clients when a task's configuration (alias, color) changes.

- **Payload:**

  ```json
  {
    "task_id": "esp32_voltmeter_01_ch1",
    "changes": { "alias": "Temp Fenster", "color": "#22c55e" },
    "propagate": true,
    "timestamp": 1690000000.123
  }
  ```

- `propagate` (boolean): If `true`, a color change at a sink should propagate upstream to the nearest source (but not beyond MATH modules).

### `persist_config`

Sent directly to a provider that has `persistConfig: true` in its manifest, requesting it to store the configuration change locally (e.g., in flash/EEPROM).

- **Payload:**

  ```json
  {
    "task_id": "my_device_01_temp",
    "alias": "Temp Fenster",
    "color": "#22c55e"
  }
  ```

- Only the changed field(s) are included (alias, color, or both).

---

## 4. Task Configuration Events (Client -> Server)

### `set_task_alias`

Sets a user-defined alias for a task (e.g., renaming "Temperature" to "Temp Fenster").

- **Payload:** `{ "task_id": "esp32_voltmeter_01_ch1", "alias": "Temp Fenster" }`
- Set `alias` to `null` to clear the alias.
- **Server Action:** Stores the alias (in SQLite if provider doesn't self-persist, or forwards to provider via `persist_config`). Broadcasts `task_config_changed` to all UI clients.

### `set_task_color`

Sets a color override for a task.

- **Payload:**

  ```json
  {
    "task_id": "esp32_voltmeter_01_ch1",
    "color": "#22c55e",
    "propagate": true
  }
  ```

- Set `color` to `null` to reset to the manifest default.
- `propagate` (optional, default `true`): Whether the color change should propagate upstream.
- **Server Action:** Stores the color override and broadcasts `task_config_changed` to all UI clients.

### `get_task_config`

Retrieves the stored configuration for a task.

- **Payload:** `{ "task_id": "esp32_voltmeter_01_ch1" }`
- **Emits Back:** `task_config` with the stored config:

  ```json
  {
    "task_id": "esp32_voltmeter_01_ch1",
    "config": { "alias": "Temp Fenster", "color": "#22c55e" }
  }
  ```
