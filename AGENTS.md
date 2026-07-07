# E-Lab – Overview

**E-Lab** is a distributed IoT measurement laboratory system that connects hardware sensors, actuators, and a modern web interface in real time. The system uses a zero-config approach (UDP discovery) for automatic device detection.

## 🚀 Key Features

- **Real-Time Data Streams:** Live streaming of measurement values via WebSockets.
- **Remote UI Loading:** Hardware clients inject their own React UI components directly into the workbench.
- **Zero-Config Discovery:** Automatic discovery of server and clients in the network via UDP.
- **Data Recording:** Recording of measurement data series in the backend.
- **Modern UI:** React 19, Vite & Tailwind CSS.

## 📂 Project Structure

- **`server.py`**: Central Flask/SocketIO dispatcher. Mediates between hardware and UI, manages sessions, and serves the web app.
- **`elab_workbench/`**: Frontend (React/Vite). The user interface of the lab.
- **`elab_clients_core/python/`**: Public Python source files for clients and shared helpers.
- **`elab_clients_premium/python/`**: Private/commercial Python clients and API examples.
- **`elab_clients_core/esp32/arduino/`**: Public Arduino sketches for ESP32 targets.
- **`elab_server/`**: Backend components (state management, discovery, recording, replay).
- **`doc/`**: Installation guides and detailed documentation.
- **`tests/`**: Backend and integration tests.

## 🛠️ Quick Start

```bash
# Backend
pip install -r requirements.txt
python server.py -d

# Frontend (separate terminal)
cd elab_workbench
npm install
npm run dev

# Simulate a client (another terminal)
python elab_clients_core/python/clients/FrequenceCounterClient.py
```

## 📖 Documentation

| Document | Content |
|----------|---------|
| **[`.github/copilot-instructions.md`](.github/copilot-instructions.md)** | ⭐ **Central AI Documentation** – Architecture, coding guidelines, agent behavior |
| [`doc/overview.md`](doc/overview.md) | Architecture overview (Data Provider Pattern) |
| [`doc/api.md`](doc/api.md) | Socket.IO event reference & protocol |
| [`doc/classes.md`](doc/classes.md) | Class diagrams & data structures |
| [`doc/install.md`](doc/install.md) | Complete installation & setup guide |
| [`doc/plugin_development.md`](doc/plugin_development.md) | Custom plugin development |
| [`doc/schema_reference.md`](doc/schema_reference.md) | Manifest schema & validation |
| [`doc/deployment.md`](doc/deployment.md) | Production setup (systemd, nginx/TLS, backup) |
| [`doc/test.md`](doc/test.md) | Test strategy & structure |

## 💡 Important for AI Agents

👉 **All AI agents should use [`.github/copilot-instructions.md`](.github/copilot-instructions.md) as their primary source.**

This central guide contains:

- Full project architecture & guidelines
- Coding standards (Python, JavaScript/React)
- Build & test workflow
- Security precautions
- Agent behavior & best practices

---

**Quick Links:**

- 🔧 [Setup & Tests](doc/install.md)
- 🏗️ [Architecture Concept](.github/copilot-instructions.md#-architektur-konzept)
- 📝 [Coding Guidelines](.github/copilot-instructions.md#-coding-richtlinien)
- ⚠️ [Common Pitfalls](.github/copilot-instructions.md#-häufige-fehler-vermeiden)
