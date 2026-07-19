# E-Lab Security — Provider Pairing & HMAC Signing

Dieses Dokument beschreibt das **Trust-on-First-Use (TOFU)**-Pairing für
E-Lab-Provider sowie die laufende HMAC-SHA256-Signierung jedes
`data_stream`-Pakets. Ziel: ein im LAN/WLAN erreichbarer Dispatcher
darf **nur** Pakete von ausdrücklich freigegebenen Geräten akzeptieren,
ohne dabei jedes Gerät vorab manuell konfigurieren zu müssen.

> Die Implementierung ist absichtlich **leicht** genug, um auch auf ESP32
> Arduino-Hardware (HW-beschleunigtes mbedTLS-HMAC) ohne TLS zu laufen.

---

## 1. Bedrohungsmodell

| Angreifer im LAN | Schutz |
|---|---|
| Schickt gefälschtes `register_provider` mit gestohlener `device_id` | Server fordert HMAC-signierte `data_stream`s; ohne Secret werden alle Pakete verworfen |
| Mitschnitt + Replay eines alten `data_stream`s | Timestamp im signierten Block (`auth.ts`) wird ggü. Serverzeit verglichen, max. Skew 300 s |
| Manipulation des Payloads on-the-fly | HMAC bricht, Paket wird verworfen |
| Wiederbenutzung eines geleakten `auto_approve_token` | Token ist **single-use** und an Server-Prozesslaufzeit gebunden |
| Manifest-Tausch nach Pairing (z.B. Task-IDs ergänzen) | Server verankert die Genehmigung an `manifest_hash` → veränderte Manifeste landen wieder in `pending` |

**Nicht** abgedeckt: vertrauliche Übertragung der Mess-Payloads (keine
Verschlüsselung). Wenn nötig, einen TLS-Reverse-Proxy davor schalten —
siehe `doc/deployment.md`.

---

## 2. Identitäts- & Lebenszyklus-Modell

```
┌─────────┐    register_provider     ┌──────────────┐
│ Device  ├─────────────────────────►│  Dispatcher  │
│ (id=X)  │                          │              │
└─────────┘                          │ ┌──────────┐ │
   ▲                                 │ │ pending  │ │  (status='pending')
   │   registration_pending ◄────────┤ └──────────┘ │
   │                                 │       │       │
   │                                 │  Operator     │
   │                                 │  klickt       │
   │                                 │  "Zulassen"   │
   │                                 │       ▼       │
   │   registration_approved         │ ┌──────────┐ │
   │   {deviceId, secret} ◄──────────┤ │ approved │ │  (status='approved')
   │                                 │ └──────────┘ │
   │                                 └──────────────┘
   ▼
[Secret in NVS/SQLite/Datei ablegen]
   │
   ▼
data_stream {... , "auth": {"sig": "<hex>", "ts": <epoch>}}
```

- **`device_id`** = `manifest.id` (vom Gerät selbst gewählt; bleibt über
  Reboots stabil).
- **`manifest_hash`** = SHA-256 über die kanonische Form des Manifests
  (`json.dumps(sort_keys=True, separators=(",", ":"))` nach Entfernen
  flüchtiger Felder).
- **`secret`** = 32 zufällige Bytes (64 Hex), einmalig vom Server an das
  Gerät gesendet, dort persistent gespeichert.

### Volatile Manifest-Felder (vor Hash gestrippt)
`sid`, `connected_at`, `client_ip`, `isUiInstance`

Diese Liste **muss** auf Server (`elab_server/auth.py`), Python-Client
(`elab_clients_core/python/shared/auth.py`) und ESP32 identisch sein.

---

## 3. HMAC-Format auf der Leitung

Jedes signierte Paket sieht so aus:

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

**MAC-Input** =
```
f"{ts:.6f}".encode("ascii") + b"\n" + canonical_payload(payload_without_auth)
```
- `canonical_payload`: `json.dumps(payload_without_auth, sort_keys=True, separators=(",",":"))`
- HMAC-SHA256 mit dem 32-Byte-Secret als Schlüssel → 64 Hex-Zeichen in `auth.sig`

**Skew-Fenster**: `|server_time - ts| > 300 s` → verworfen.

> **Achtung ESP32:** Da die ESP32-Firmware das Paket selbst byte-weise
> baut, muss sie die Schlüssel des inneren Objekts **bereits in
> alphabetischer Reihenfolge** ausgeben (`distribution`, `endTime`,
> `raw_bytes`, `sourceId`, `startTime`). Der `auth`-Block wird **nach**
> dem Signieren angehängt und absichtlich an der Sortierung vorbei
> eingefügt; der Server entfernt ihn vor der Re-Kanonisierung.

---

## 4. Socket.IO-Events

### Server → Client
| Event | Payload | Zweck |
|---|---|---|
| `registration_pending` | `{deviceId, manifestHash}` | Gerät wartet auf Operator-Freigabe |
| `registration_approved` | `{deviceId, secret, manifestHash}` | Einmalige Auslieferung des Secrets |
| `registration_revoked` | `{deviceId, reason?}` | Operator hat das Gerät blockiert |
| `pending_devices` | `[{deviceId, manifest, manifestHash, clientIp, firstSeenAt, sid}, ...]` | Aktuelle Pending-Liste für die UI |

### Client → Server (Provider)
| Event | Payload | Zweck |
|---|---|---|
| `register_provider` | `<manifest>` (optional: `auto_approve_token`) | Registrierungsanfrage |
| `data_stream` | `<payload>` mit signiertem `auth`-Block | Live-Datenpaket |

### UI → Server (Operator)
| Event | Payload | Zweck |
|---|---|---|
| `get_pending_devices` | — | Pending-Liste anfordern |
| `approve_pending_device` | `{deviceId, manifestHash}` | Pairing genehmigen |
| `revoke_device` | `{deviceId}` | Gerät trennen + Schlüssel zurückziehen |
| `delete_device_credential` | `{deviceId}` | Eintrag komplett löschen |

---

## 5. Konfiguration (Env-Variablen)

| Variable | Wirkung | Default |
|---|---|---|
| `ELAB_REQUIRE_AUTH` | Bei `0`/`false`/`no`/`off` wird die HMAC-Prüfung **deaktiviert** (nur für Tests / Migration) | `true` |
| `ELAB_AUTO_APPROVE_TOKEN` | Wird vom `ProcessManager` für lokal gespawnte Skripte gesetzt → automatische Freigabe ohne Operator-Klick | unset |
| `ELAB_CLIENT_CREDENTIALS_DIR` | Speicherort der persistenten Client-Secrets (Python) | `~/.elab/credentials/` |

---

## 6. Speicherorte

| Speicher | Inhalt |
|---|---|
| **Server-DB** `elab_server/elab_config.sqlite` Tabelle `provider_credentials` | `device_id`, `secret_hex`, `manifest_hash`, `status`, Timestamps |
| **Python-Client** `~/.elab/credentials/<device_id>.json` (chmod 600 auf POSIX) | `{device_id, secret_hex, saved_at}` |
| **ESP32** NVS Namespace `elab_auth`, Key `secret` | Hex-String, 64 Zeichen |

---

## 7. Operative Szenarien

### Neues Gerät einbinden
1. Gerät einschalten → meldet sich mit `register_provider`.
2. Workbench → Sidebar → Sektion **"Registrierung"** zeigt das Gerät.
3. Operator klickt **"Zulassen"**.
4. Dispatcher sendet `registration_approved` inkl. Secret.
5. Gerät speichert Secret persistent und beginnt mit signierten
   `data_stream`s.

### Gerät tauschen / Firmware-Update mit Manifest-Änderung
- Beim nächsten Connect erkennt der Server einen neuen `manifest_hash`.
- Status wird automatisch auf `pending` zurückgesetzt → Operator muss
  erneut zulassen. Das ursprüngliche Secret wird verworfen.

### Gerät verloren / kompromittiert
- Operator klickt **"Ablehnen"** in der Registrierungs-Sektion (oder bei
  einem bereits genehmigten Gerät den Revoke-Button).
- Dispatcher trennt die Verbindung und sendet `registration_revoked`.
- Bei zukünftigen Reconnects landet das Gerät wieder in `pending`.

### Auto-Pairing lokal gestarteter Skripte
- `ProcessManager.start_script(...)` ruft `make_auto_approve_token()`
  und setzt `ELAB_AUTO_APPROVE_TOKEN` im Child-Prozess.
- Das gestartete Skript reicht den Token via `register_provider.auto_approve_token`
  durch.
- Dispatcher verbraucht den Token einmalig, springt direkt in
  `approved` und sendet das Secret zurück.

---

## 8. Troubleshooting

| Symptom | Ursache | Lösung |
|---|---|---|
| `data_stream HMAC verify failed: signature mismatch` | Kanonisierung weicht auf Client und Server ab (z.B. ungewollt veränderte Volatile-Liste, falsche Key-Reihenfolge auf ESP32) | Sicherstellen, dass `_VOLATILE_MANIFEST_FIELDS` synchron ist; ESP32-JSON in alphabetischer Reihenfolge bauen |
| `data_stream HMAC verify failed: timestamp skew exceeds limit` | Geräte-Uhr läuft falsch (ESP32 ohne NTP) | NTP auf dem Gerät aktivieren (`configTime(...)`); ggf. Skew-Fenster anpassen |
| Gerät erscheint nicht in der Registrierungs-Sektion | UI hat `pending_devices` noch nicht abgefragt | Workbench neu laden oder `get_pending_devices` triggern |
| ESP32 verwirft Frames mit `[AUTH] Geraet noch nicht freigegeben` | Kein Secret in NVS | In Workbench freigeben; ESP32 speichert Secret beim nächsten `registration_approved` |
| Nach Server-Wipe rückt Gerät nicht in `pending` | Gerät hat noch gültiges Secret im NVS/Datei und sendet sofort `data_stream` (das verworfen wird, weil Server-DB leer ist) | Secret auf dem Gerät löschen (NVS `elab_auth` flashen / `~/.elab/credentials/<id>.json` löschen), dann reconnect |

---

## 9. Tests

```powershell
# Server-Auth (Canonicalization, HMAC, ConfigStore, SystemState)
pytest tests/test_provider_auth.py -v

# Client-Helper (Persistence, Sign/Verify Interop, Revoke, Auto-Token)
pytest tests/test_client_auth.py -v
```

Beide Suites laufen ohne laufenden Dispatcher und nutzen
isolierte tmp-Verzeichnisse für SQLite + Credentials.

---

## 10. Migrationshinweis

Bestehende Installationen, die das Update einspielen, ohne dass die
Geräte mit neuer Firmware/Client-Lib laufen, werden alle eingehenden
`data_stream`-Pakete verwerfen. Übergang:

1. Server aktualisieren (HMAC-Prüfung **aktiv**).
2. Mit `ELAB_REQUIRE_AUTH=0` starten, solange noch Legacy-Geräte im
   Einsatz sind.
3. Geräte sukzessive aktualisieren und in der Workbench freigeben.
4. Wenn alle Geräte umgestellt sind, `ELAB_REQUIRE_AUTH` wieder
   entfernen → Default `true`.

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
