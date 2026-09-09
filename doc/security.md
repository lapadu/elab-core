# E-Lab Security - Provider Pairing & HMAC Signing

This document describes **Trust on First Use (TOFU)** pairing for E-Lab
providers and ongoing HMAC-SHA256 signing of every `data_stream` packet from
an external provider. The goal is that a dispatcher reachable on the LAN/WLAN
accepts packets **only** from explicitly approved devices without requiring
every device to be configured manually in advance.

> The implementation is intentionally **lightweight** enough to run on ESP32
> Arduino hardware using hardware-accelerated mbedTLS HMAC without TLS.

---

## 1. Threat Model

| LAN attacker | Protection |
|---|---|
| Sends a forged `register_provider` with a stolen `device_id` | The server requires HMAC-signed `data_stream` packets; without the secret, all packets are rejected |
| Captures and replays an old `data_stream` packet | The timestamp in the signed block (`auth.ts`) is checked against server time, with a maximum skew of 300 s |
| Modifies the payload in transit | The HMAC fails and the packet is rejected |
| Reuses a leaked `auto_approve_token` | The token is **single-use** and exists only for the lifetime of the server process |
| Changes the manifest after pairing (for example, adds task IDs) | The server binds approval to `manifest_hash`; changed manifests return to `pending` |

**Not** covered: confidentiality of measurement payloads (there is no
encryption). If required, place a TLS reverse proxy in front of the service;
see `doc/deployment.md`.

UI-internal virtual providers are a deliberate exception: the workbench marks
their source IDs as trusted, so they bypass TOFU/HMAC. This applies only to
sources created by the trusted UI path, not to external Python scripts,
hardware clients, or Local API Bridge providers.

---

## 2. Identity and Lifecycle Model

```
┌─────────┐    register_provider     ┌──────────────┐
│ Device  ├─────────────────────────►│  Dispatcher  │
│ (id=X)  │                          │              │
└─────────┘                          │ ┌──────────┐ │
   ▲                                 │ │ pending  │ │  (status='pending')
   │   registration_pending ◄────────┤ └──────────┘ │
   │                                 │       │       │
   │                                 │  Operator     │
  │                                 │  clicks       │
  │                                 │  "Approve"   │
   │                                 │       ▼       │
   │   registration_approved         │ ┌──────────┐ │
   │   {deviceId, secret} ◄──────────┤ │ approved │ │  (status='approved')
   │                                 │ └──────────┘ │
   │                                 └──────────────┘
   ▼
[Store secret in NVS/SQLite/file]
   │
   ▼
data_stream {... , "auth": {"sig": "<hex>", "ts": <epoch>}}
```

* **`device_id`** = `manifest.device.id`, the identifier of the physical or
  logical unit. Manifests without a `device` block fall back to `manifest.id`
  for legacy compatibility. Multiple providers from the same device share
  **one** credential.
* **`device.anchor`** states where the identifier came from (`efuse_mac`,
  `serial`, `ble_mac`, `assigned`, `ephemeral`). Every anchor except
  `ephemeral` is expected to survive a restart. `ephemeral` devices must be
  approved again after every start and are marked accordingly in the workbench.
* **`manifest_hash`** = SHA-256 over the canonical manifest representation
  (`json.dumps(sort_keys=True, separators=(",", ":"))` after volatile fields
  are removed).
* **`secret`** = 32 random bytes (64 hex characters), sent once by the server
  to the device and stored persistently. Ephemeral credentials are kept only
  in memory for the current session.

### Binding the data stream to the session

In addition to HMAC verification, `data_stream` is checked against the sending
session: only the Socket.IO session that registered a `sourceId` may send data
for it. A valid secret alone is not sufficient.

### Volatile manifest fields stripped before hashing
`sid`, `connected_at`, `client_ip`, `isUiInstance`

This list **must** remain identical in the server (`elab_server/auth.py`),
Python client (`elab_clients_core/python/shared/auth.py`), and ESP32 firmware.

---

## 3. HMAC Wire Format

Every signed packet looks like this:

```json
{
  "sourceId": "esp32_voltmeter_01_ch1",
  "distribution": "linear",
  "startTime": 12345,
  "endTime": 12446,
  "raw_bytes": [0, 1, 2, ...],
  "auth": {
    "sig": "5e7f...d12c",
    "ts": 1735052819.123456
  }
}
```

**MAC input** =
```
f"{ts:.6f}".encode("ascii") + b"\n" + canonical_payload(payload_without_auth)
```
- `canonical_payload`: `json.dumps(payload_without_auth, sort_keys=True, separators=(",",":"))`
- HMAC-SHA256 with the 32-byte secret as the key -> 64 hex characters in `auth.sig`

**Skew window**: `|server_time - ts| > 300 s` -> rejected.

> **ESP32 note:** Because the ESP32 firmware builds the packet byte by byte,
> it must output the keys of the inner object in **alphabetical order**
> (`distribution`, `endTime`, `raw_bytes`, `sourceId`, `startTime`). The `auth`
> block is appended **after** signing and intentionally added outside that
> ordering; the server removes it before re-canonicalizing the payload.

---

## 4. Socket.IO Events

### Server -> Client
| Event | Payload | Purpose |
|---|---|---|
| `registration_pending` | `{deviceId, manifestHash}` | Device is waiting for operator approval |
| `registration_approved` | `{deviceId, secret, manifestHash}` | One-time delivery of the secret |
| `registration_revoked` | `{deviceId, reason?}` | Operator revoked the device |
| `pending_devices` | `[{deviceId, manifest, manifestHash, clientIp, firstSeenAt, sid}, ...]` | Current pending list for the UI |

### Client -> Server (provider)
| Event | Payload | Purpose |
|---|---|---|
| `register_provider` | `<manifest>` (optional: `auto_approve_token`) | Registration request |
| `data_stream` | `<payload>` with signed `auth` block | Live data packet |

### UI -> Server (operator)
| Event | Payload | Purpose |
|---|---|---|
| `get_pending_devices` | - | Request the pending list |
| `approve_pending_device` | `{deviceId, manifestHash}` | Approve pairing |
| `revoke_device` | `{deviceId}` | Disconnect the device and revoke its key |
| `delete_device_credential` | `{deviceId}` | Delete the entry completely |

---

## 5. Configuration (Environment Variables)

| Variable | Effect | Default |
|---|---|---|
| `ELAB_REQUIRE_AUTH` | Set to `0`/`false`/`no`/`off` to **disable** HMAC verification (tests or migration only) | `true` |
| `ELAB_AUTO_APPROVE_TOKEN` | Set by `ProcessManager` for locally spawned scripts -> automatic approval without an operator click | unset |
| `ELAB_CLIENT_CREDENTIALS_DIR` | Storage location for persistent Python client secrets | `~/.elab/credentials/` |

---

## 6. Storage Locations

| Storage | Contents |
|---|---|
| **Server database** `elab_server/elab_config.sqlite`, table `provider_credentials` | `device_id`, `secret_hex`, `manifest_hash`, `status`, timestamps |
| **Python client** `~/.elab/credentials/<device_id>.json` (`chmod 600` on POSIX) | `{device_id, secret_hex, saved_at}` |
| **ESP32** NVS namespace `elab_auth`, key `secret` | 64-character hex string |

---

## 7. Operational Scenarios

### Add a new device
1. Power on the device; it registers with `register_provider`.
2. In the workbench, the **"Registration"** section in the sidebar shows the device.
3. The operator clicks **"Approve"**.
4. The dispatcher sends `registration_approved` with the secret.
5. The device stores the secret persistently and starts sending signed
   `data_stream` packets.

### Replace a device or update firmware with a manifest change
- On the next connection, the server detects a new `manifest_hash`.
- The status is automatically reset to `pending`; the operator must approve it
  again. The original secret is discarded.

### Device lost or compromised
- The operator clicks **"Reject"** in the Registration section (or the Revoke
  button for an already approved device).
- The dispatcher disconnects the device and sends `registration_revoked`.
- On future reconnects, the device returns to `pending`.

### Auto-pairing locally spawned scripts
- `ProcessManager.start_script(...)` calls `make_auto_approve_token()` and sets
  `ELAB_AUTO_APPROVE_TOKEN` in the child process.
- The spawned script forwards the token as `register_provider.auto_approve_token`.
- The dispatcher consumes the token once, transitions directly to `approved`,
  and sends the secret back.

---

## 8. Troubleshooting

| Symptom | Cause | Solution |
|---|---|---|
| `data_stream HMAC verify failed: signature mismatch` | Canonicalization differs between client and server (for example, an accidentally changed volatile-field list or incorrect key order on ESP32) | Ensure `_VOLATILE_MANIFEST_FIELDS` is synchronized; build ESP32 JSON in alphabetical order |
| `data_stream HMAC verify failed: timestamp skew exceeds limit` | Device clock is incorrect (ESP32 without NTP) | Enable NTP on the device (`configTime(...)`); adjust the skew window if necessary |
| Device does not appear in the Registration section | The UI has not requested `pending_devices` yet | Reload the workbench or trigger `get_pending_devices` |
| ESP32 rejects frames with `[AUTH] Geraet noch nicht freigegeben` | No secret is stored in NVS | Approve the device in the workbench; the ESP32 stores the secret on the next `registration_approved` |
| Device does not return to `pending` after a server wipe | The device still has a valid secret in NVS or a file and immediately sends `data_stream` (which is rejected because the server database is empty) | Delete the device secret (flash NVS `elab_auth` or delete `~/.elab/credentials/<id>.json`), then reconnect |

---

## 9. Tests

```powershell
# Server-Auth (Canonicalization, HMAC, ConfigStore, SystemState)
pytest tests/test_provider_auth.py -v

# Client-Helper (Persistence, Sign/Verify Interop, Revoke, Auto-Token)
pytest tests/test_client_auth.py -v
```

Both suites run without a running dispatcher and use isolated temporary
directories for SQLite and credentials.

---

## 10. Migration Note

Existing installations that apply the update before their devices run the new
firmware or client library will reject all incoming `data_stream` packets.
Migration path:

1. Update the server (HMAC verification **enabled**).
2. Start with `ELAB_REQUIRE_AUTH=0` while legacy devices are still in use.
3. Update the devices incrementally and approve them in the workbench.
4. Once all devices have been migrated, remove `ELAB_REQUIRE_AUTH` again;
  the default is `true`.

---

## 11. Managing the Discovery Service in the Local Network

By default, the E-Lab Dispatcher sends UDP broadcast packets so that clients in the local network can automatically discover and connect to the server ("zero-config"). In restrictive networks or for security reasons, this service can be disabled at runtime.

### Control Endpoints

The discovery service can be controlled via REST API calls:

- **Disable Discovery:**
  ```bash
  # Windows PowerShell users: use curl.exe instead of curl
  curl.exe -X POST http://<server-ip>:5000/api/discovery/disable
  ```
  *(Prevents the server from sending further UDP broadcasts)*

- **Enable Discovery:**
  ```bash
  curl.exe -X POST http://<server-ip>:5000/api/discovery/enable
  ```

- **Check Status:**
  ```bash
  curl.exe http://<server-ip>:5000/api/discovery/status
  ```
  *(Responds with e.g. `{"enabled": true}`)*

**Note:** Disabling this service only affects the automatic device discovery. Existing TCP/WebSocket connections and clients that connect using a hardcoded IP address will remain fully functional.
