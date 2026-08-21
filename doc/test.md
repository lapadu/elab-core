# E-Lab – Testausführung & Coverage

## Voraussetzungen

```bash
# Virtual Environment aktivieren
.venv\Scripts\activate        # Windows
source .venv/bin/activate     # Linux/Mac

# Test-Abhängigkeiten (in requirements.txt enthalten)
pip install -r requirements.txt
```

---

## Backend-Tests (pytest)

### Alle Tests ausführen

```bash
pytest -q
```

### Mit ausführlicher Ausgabe

```bash
pytest -v
```

### Einzelnes Testmodul

```bash
pytest tests/test_state.py -v
pytest tests/integration/test_sockets.py -v
```

### Coverage-Report (Terminal)

```bash
pytest --cov=elab_server --cov-report=term-missing
```

### Coverage-Report (HTML)

```bash
pytest --cov=elab_server --cov-report=html
# Öffnet sich unter htmlcov/index.html
```

---

## Frontend-Tests (Vitest)

### Alle Tests ausführen

```bash
cd elab_workbench
npm test
```

### Watch-Mode (entwicklungsbegleitend)

```bash
npm test -- --watch
```

### Coverage-Report

```bash
npm test -- --coverage
```

---

## Teststruktur

```
conftest.py                        # Globale Fixtures (sys.path) – im Repo-Root
tests/
├── test_decoders.py               # Decoder-Logik
├── test_decoders_extended.py      # Erweiterte Decoder-Tests
├── test_discovery.py              # UDP-Discovery
├── test_manifest_builder.py       # Manifest-Validierung
├── test_plugin_security.py        # Plugin-URL-Sicherheit
├── test_process_manager.py        # Client-Prozessverwaltung
├── test_replayer.py               # Session-Replayer
├── test_state.py                  # SystemState-Registry
└── integration/
    ├── conftest.py                # Flask-SocketIO Test-Client Fixture
    ├── test_sockets.py            # Socket.IO Event-Handler (End-to-End)
    └── test_sessions.py           # Session-Recording & Replay

elab_workbench/src/
├── services/*.test.js             # DispatcherClient, FactoryManager
├── plugins/core/*.test.js         # PluginBuilder
├── reducers/*.test.js             # Slot-Reducer
└── utils/*.test.js                # FFT, Downsampling, Streaming, Events
```

---

## Integration-Tests

Die Integration-Tests unter `tests/integration/` starten den kompletten Server-Stack
in-process (kein Netzwerk-Port nötig) über Flask-SocketIOs eingebauten Test-Client.

```bash
# Nur Integration-Tests
pytest tests/integration/ -v
```

Getestete Bereiche:

- Verbindungsaufbau & Client-Registrierung
- Provider-Registrierung & Manifest-Validierung
- `data_stream`-Weiterleitung an UI-Clients
- Task-Assignment & Slot-Verwaltung
- `cmd_control`-Forwarding
- Session-Aufnahme (SQLite-Verifizierung)
- Session-Verwaltung & Löschung (inkl. Path-Traversal-Schutz)
- Replay-Laden & Recorded-Provider-Auflösung

---

## Konfiguration

| Datei             | Zweck                                     |
| ----------------- | ----------------------------------------- |
| `pytest.ini`      | Test-Discovery, Filter, Default-Argumente |
| `setup.cfg`       | Pylint-Konfiguration                      |
| `vitest.setup.js` | Frontend-Test-Setup (jsdom, Mocks)        |

---

## CI-Empfehlung

```bash
# Backend
pytest --cov=elab_server --cov-report=xml --cov-fail-under=50

# Frontend
cd elab_workbench && npm test -- --coverage --reporter=junit
```
