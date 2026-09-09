# E-Lab - Test Execution & Coverage

## Requirements

```bash
# Activate the virtual environment
.venv\Scripts\activate        # Windows
source .venv/bin/activate     # Linux/Mac

# Test dependencies (included in requirements.txt)
pip install -r requirements.txt
```

---

## Backend Tests (pytest)

### Run all tests

```bash
pytest -q
```

### Verbose output

```bash
pytest -v
```

### Individual test module

```bash
pytest tests/test_state.py -v
pytest tests/integration/test_sockets.py -v
```

### Coverage report (terminal)

```bash
pytest --cov=elab_server --cov-report=term-missing
```

### Coverage report (HTML)

```bash
pytest --cov=elab_server --cov-report=html
# Open htmlcov/index.html
```

---

## Frontend Tests (Vitest)

### Run all tests

```bash
cd elab_workbench
npm test
```

### Watch mode (during development)

```bash
npm test -- --watch
```

### Coverage report

```bash
npm test -- --coverage
```

---

## Test Structure

```
conftest.py                        # Global fixtures (sys.path) - in the repository root
tests/
├── test_decoders.py               # Decoder logic
├── test_decoders_extended.py      # Extended decoder tests
├── test_discovery.py              # UDP discovery
├── test_manifest_builder.py       # Manifest validation
├── test_plugin_security.py        # Plugin URL security
├── test_process_manager.py        # Client process management
├── test_replayer.py               # Session replayer
├── test_state.py                  # SystemState registry
└── integration/
    ├── conftest.py                # Flask-SocketIO test client fixture
    ├── test_sockets.py            # Socket.IO event handlers (end-to-end)
    └── test_sessions.py           # Session recording and replay

elab_workbench/src/
├── services/*.test.js             # DispatcherClient, FactoryManager
├── plugins/core/*.test.js         # PluginBuilder
├── reducers/*.test.js             # Slot reducer
└── utils/*.test.js                # FFT, downsampling, streaming, events
```

---

## Integration Tests

The integration tests in `tests/integration/` start the complete server stack
in-process (no network port required) through Flask-SocketIO's built-in test client.

```bash
# Integration tests only
pytest tests/integration/ -v
```

Covered areas:

- Connection establishment and client registration
- Provider registration and manifest validation
- `data_stream` forwarding to UI clients
- Task assignment and slot management
- `cmd_control` forwarding
- Session recording (SQLite verification)
- Session management and deletion (including path traversal protection)
- Replay loading and recorded provider resolution

---

## Configuration

| File              | Purpose                                   |
| ----------------- | ----------------------------------------- |
| `pytest.ini`      | Test discovery, filters, default arguments |
| `setup.cfg`       | Pylint configuration                      |
| `vitest.setup.js` | Frontend test setup (jsdom, mocks)        |

---

## CI Recommendation

```bash
# Backend
pytest --cov=elab_server --cov-report=xml --cov-fail-under=50

# Frontend
cd elab_workbench && npm test -- --coverage --reporter=junit
```
