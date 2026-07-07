# Copilot Instructions – E-Lab

**Zentrale KI-Dokumentation für das E-Lab Projekt.** Alle KI-Agenten sollten diese Anleitung als primäre Quelle nutzen.

---

## 📋 Projektübersicht

**E-Lab** ist ein verteiltes IoT-Messlabor-System, das Hardware-Sensoren, Aktoren und eine moderne Web-Oberfläche in Echtzeit verbindet. Das System nutzt einen Zero-Config-Ansatz (UDP-Discovery) für automatische Geräteerkennung.

### 🎯 Kernfeatures

- **Echtzeit-Datenströme:** Live-Streaming von Messwerten über WebSockets
- **Remote UI Loading:** Hardware-Clients injizieren eigene React-UI-Komponenten direkt in die Workbench
- **Zero-Config Discovery:** Automatische Erkennung von Server und Clients im Netzwerk via UDP
- **Datenaufzeichnung:** Recording von Messdatenreihen im Backend
- **Moderne UI:** React 19, Vite & Tailwind CSS

### 📂 Projektstruktur

```
E-Lab/
├── server.py                    # Zentrale Flask/SocketIO Dispatcher
├── conftest.py                  # Root pytest-Konfiguration
├── pytest.ini                   # Pytest-Einstellungen
├── pyrightconfig.json           # Pyright/Pylance Typ-Checking
├── requirements.txt             # Python-Abhängigkeiten
├── setup.cfg                    # Pylint-Konfiguration
│
├── elab_server/                 # Backend: Server-Komponenten
│   ├── app.py                   # Flask/SocketIO Setup
│   ├── state.py                 # SystemState Registry
│   ├── discovery.py             # UDP Discovery
│   ├── process_manager.py       # Client-Prozessverwaltung
│   ├── manifest_builder.py      # Manifest-Validierung
│   ├── recorder.py              # Session-Recording
│   └── replayer.py              # Session-Replay
│
├── elab_clients_core/
│   ├── python/
│   │   ├── clients/             # Öffentliche Python-Client-Implementierungen
│   │   ├── shared/              # Gemeinsame Python-Helfer
│   │   └── assets/              # Frontend-Plugin-Assets für Python-Clients
│   └── esp32/
│       └── arduino/
├── elab_clients_premium/
│   └── python/
│       └── api/                 # Private/kommerzielle Bridge/API-Beispiele
│
├── elab_workbench/              # Frontend: React/Vite UI
│   ├── src/
│   ├── package.json
│   ├── vite.config.js
│   ├── eslint.config.js
│   ├── tailwind.config.js
│   └── vitest.setup.js
│
├── elab_electron/               # Electron-Desktop-App
├── doc/                         # Dokumentation
│   ├── overview.md              # Architektur-Übersicht
│   ├── api.md                   # Socket.IO Event-Referenz
│   ├── classes.md               # Klassen-Diagramme
│   ├── plugin_development.md    # Plugin-Entwicklung
│   ├── schema_reference.md      # Manifest-Schema
│   ├── deployment.md            # Produktion (systemd, nginx, TLS, Backup)
│   ├── install.md               # Installationsanleitung
│   └── test.md                  # Test-Architektur
│
├── tests/                       # Backend-Tests
│   ├── test_*.py                # Unit-Tests (pytest)
│   └── integration/
│       └── test_*.py            # Integrations-Tests (SocketIO)
│
└── .github/
    └── copilot-instructions.md  # Diese Datei
```

---

## 🏗️ Architektur-Konzept

Das E-Lab-System folgt einer **entkoppelten Architektur**, die Datenprovider von Datenkonsumenten trennt. Der zentrale `server.py` fungiert als Dispatcher.

### Task Provider & Registrierung

- **Provider-Rolle:** Clients (Hardware-Sensoren, Simulatoren) sind **Task Provider**
- **Registrierung:** Beim Start melden sich Provider beim Dispatcher an und registrieren ihre Datenaufgaben (z.B. "Temperatur bereitstellen", "Frequenz messen")
- **Persistente Datenströme:** Provider senden kontinuierlich Daten an den Dispatcher, unabhängig davon, ob die UI zuhört

### Entkopplung von Daten und Anzeige

**Kern-Prinzip:** Strikte Trennung zwischen Datenerzeugung und Visualisierung.

- **Kontinuierlicher Datenfluss:** Task Provider streamen ständig Daten zum Dispatcher
- **UI-Subscription:** Die Workbench (Web-Frontend) ist ein Datenkonsument. Wenn ein Benutzer ein Widget auf sein Grid zieht, **abonniert die UI den entsprechenden Datenstrom** – der Server beginnt dann, Daten an diesen spezifischen Client zu senden
- **Daten-Pausieren:** Wenn der Benutzer ein Widget pausiert oder löscht, stoppt der Server nur die Weiterleitung an die UI. Der Sensor sende seine Daten **unverändert weiter**
- **Session & Buffering:** Der Dispatcher kann Datenströme zwischenspeichern, auch wenn die UI offline ist – für historische Replay oder Offline-Analyse

### Zukünftig: Display Triggers

Geplante Features für UI-seitige oder Server-seitige Regeln, die **nur die Anzeige** beeinflussen (z.B. "nur Werte > X anzeigen"), nicht den Rohdatenstrom.

---

## 💎 Richtlinien & Workflow für KI-Agenten

### Agent-Verhalten (Essentiell)

1. **Vor Änderungen:** Lies relevante Dateien und Konfigurationen
2. **Bei Unklarheit:** Frage nach, wenn Anforderungen unklar oder Nebenwirkungen möglich sind
3. **Architektur-Integrität:** Behalte die Provider-Consumer-Trennung ein (Provider liefern Daten, UI subscribed)
4. **Keine stillen API-Änderungen:** Frage vor fundamentalen Änderungen bestehender APIs
5. **Code-Stil:** Analysiere umgebenden Code und kopiere Konventionen (Naming, Struktur, Muster)
6. **Test-First:** Neue Features sollten Tests haben, bevor sie Produktion gehen

### Sicherheitsvorkehrungen

- **ESP32-Clients:** Zu schwach für TLS/Verschlüsselung → **Bevorzuge Signing/Auth statt Payload-Verschlüsselung**
- **Path-Traversal-Schutz:** Siehe `elab_server/process_manager.py:_SCRIPT_FILENAME_RE` als Referenz
- **Plugin-URL-Validierung:** Siehe `elab_clients_core/python/shared/plugin_security.py` für sichere URL-Behandlung

---

## 🗂️ Coding-Richtlinien

### Allgemein

| Aspekt | Vorgabe |
|--------|---------|
| **Sprache** | Code, Variablen, Kommentare & Dokumentation: Englisch. Kommunikation mit Entwickler: Deutsch (oder Englisch nach Bedarf) |
| **Tests** | Neue Features & Bug-Fixes sollten Tests haben |
| **Commits** | Aussagekräftige Commit-Messages, atomare Änderungen |

### Python (`server.py`, `elab_server/`, `elab_clients_core/python/`, `elab_clients_premium/python/`)

- **Style Guide:** PEP 8 (Black-Format, 100er Zeilenlänge wo möglich)
- **Type Hints:** Pflicht – verbessert Wartbarkeit
- **Linting:** `pylint` mit Konfiguration in `setup.cfg`
- **Type Checking:** Pyright via `pyrightconfig.json`
- **Tests:** pytest in `tests/`, Integrations-Tests in `tests/integration/`

**Layout-Hinweis:** Öffentliche Python-Client-Implementierungen gehören unter `elab_clients_core/python/clients/`. Öffentliche API-Beispiele gehören unter `elab_clients_core/python/api/`; private/kommerzielle API-Beispiele unter `elab_clients_premium/python/api/`.

**Beispiel:**
```python
def process_data(value: int, metadata: dict[str, Any]) -> tuple[bool, str]:
    """Process measurement data and validate.
    
    Args:
        value: Messwert
        metadata: Zusätzliche Kontext-Daten
    
    Returns:
        (success, message) Tuple
    """
    if value < 0:
        return False, "Value must be non-negative"
    return True, "OK"
```

### JavaScript/React (`elab_workbench/`)

- **Style:** Folge `eslint.config.js` (`npm run lint` zur Prüfung)
- **Formatting:** `npm run format` (Prettier, Config in `.prettierrc.json`)
- **Components:** Funktionale Komponenten mit Hooks
- **Naming Conventions:**
  - `PascalCase` für Komponenten-Dateien und Namen (z.B. `DeviceTree.jsx`)
  - `camelCase` für Funktionen und Variablen
  - `UPPER_CASE` für Konstanten
- **Tests:** Vitest in `elab_workbench/src/**/*.test.js`

**Beispiel:**
```jsx
function SensorWidget({ sensorId, onValueChange }) {
  const [value, setValue] = useState(null);
  
  useEffect(() => {
    onValueChange?.(value);
  }, [value, onValueChange]);
  
  return <div>{value}</div>;
}
```

---

## 🔧 Build & Test Workflow

### Frontend (`elab_workbench/`)

```bash
# Install dependencies
npm install

# Development server
npm run dev

# Linting & Formatting
npm run lint
npm run format

# Type checking
npm run generate-types

# Testing
npm test
npm test -- --coverage

# Build for production
npm run build
```

### Backend (Python)

```bash
# Install dependencies (with venv)
pip install -r requirements.txt

# Linting
pylint elab_server elab_clients

# Type checking
pyright

# Testing
pytest -q
pytest --cov=elab_server tests/

# Running server
python server.py -d  # Debug mode
```

### Complete Test Suite

```bash
# Windows PowerShell
.\tests\test-all.ps1

# With coverage
.\tests\test-all.ps1

# Backend only
.\tests\test-all.ps1 -BackendOnly

# Frontend only
.\tests\test-all.ps1 -FrontendOnly
```

---

## 📋 Formatting & Linting Checklist

| Komponente | Tool | Befehl | Config |
|------------|------|--------|--------|
| Frontend-Lint | ESLint | `npm run lint` | `elab_workbench/eslint.config.js` |
| Frontend-Format | Prettier | `npm run format` | `elab_workbench/.prettierrc.json` |
| Backend-Lint | Pylint | `pylint elab_server` | `setup.cfg` |
| Backend-Types | Pyright | `pyright` | `pyrightconfig.json` |
| Backend-Tests | pytest | `pytest -q` | `pytest.ini` |
| Frontend-Tests | Vitest | `npm test` | `elab_workbench/vitest.setup.js` |

---

## 🚀 Änderungen & Migrationen

### Migrations-Pflicht

Wenn eine Verhaltensänderung stattfindet:
1. **Dokumentation:** Kurzer Migrationshinweis in `doc/` oder relevanter README
2. **Abhängigkeiten:** Neue Dependencies müssen begründet sein
3. **Große Änderungen:** Aktualisiere diese Datei, sodass sie konsistent bleibt

### Breaking Changes

- **Server-API-Änderungen:** Aktualisiere `doc/api.md`
- **Schema-Änderungen:** Aktualisiere `schemas/ManifestSchema.json` + `doc/schema_reference.md`
- **Client-Protocol:** Bespreche im PR; "nicht zu schwach für ESP32" bleibt Constrain

---

## 📚 Weitere Ressourcen

| Dokument | Inhalt |
|----------|--------|
| [`doc/overview.md`](../doc/overview.md) | High-level Architektur-Übersicht |
| [`doc/api.md`](../doc/api.md) | Socket.IO Event-Referenz & Protokoll |
| [`doc/classes.md`](../doc/classes.md) | Klassen-Diagramme & Datenstrukturen |
| [`doc/plugin_development.md`](../doc/plugin_development.md) | Anleitung für Custom-Plugins |
| [`doc/schema_reference.md`](../doc/schema_reference.md) | Manifest-Schema & Validierung |
| [`doc/install.md`](../doc/install.md) | Installations- & Setup-Anleitung |
| [`doc/deployment.md`](../doc/deployment.md) | Production (systemd, nginx/TLS, Backup) |
| [`doc/test.md`](../doc/test.md) | Test-Strategie & -Struktur |
| [`AGENTS.md`](../AGENTS.md) | Projekt-Übersicht (Schnelleinstieg) |

---

## ⚠️ Häufige Fehler (Vermeiden!)

- ❌ API-Änderungen ohne Rückfrage im PR
- ❌ Code ohne Type Hints (Python) oder Tests (generell)
- ❌ Verschlüsselung von Payloads für ESP32-Clients (zu ressourcenintensiv)
- ❌ Provider-Consumer-Trennung verletzten (z.B. Data-Pump stoppen, wenn UI disconnectet)
- ❌ Formatting/Linting nicht vor Commit checken
- ❌ Große Refactorings ohne separates Issue/Diskussion

---

## 🔐 Sichere Praktiken

1. **Path Traversal:** Regex-Validierung vor Datei-Operationen (siehe `_SCRIPT_FILENAME_RE` in `elab_server/process_manager.py`)
2. **Plugin-URLs:** Whitelist & Validierung (siehe `elab_clients_core/python/shared/plugin_security.py`)
3. **Session-IDs:** Secure Randomization, kein User-Input
4. **Logging:** Keine Secrets, Tokens oder sensiven Daten im Log
5. **Dependencies:** Minimale, gut-gepflegte Pakete; regelmäßig updaten
