# E-Lab – Übersicht

**E-Lab** ist ein verteiltes IoT-Messlabor-System, das Hardware-Sensoren, Aktoren und eine moderne Web-Oberfläche in Echtzeit verbindet. Das System nutzt einen Zero-Config-Ansatz (UDP-Discovery) für automatische Geräteerkennung.

## 🚀 Kernfeatures

- **Echtzeit-Datenströme:** Live-Streaming von Messwerten über WebSockets
- **Remote UI Loading:** Hardware-Clients injizieren eigene React-UI-Komponenten direkt in die Workbench
- **Zero-Config Discovery:** Automatische Erkennung von Server und Clients im Netzwerk via UDP
- **Datenaufzeichnung:** Recording von Messdatenreihen im Backend
- **Moderne UI:** React 19, Vite & Tailwind CSS

## 📂 Projektstruktur

- **`server.py`**: Zentrale Flask/SocketIO Dispatcher. Vermittelt zwischen Hardware und UI, verwaltet Sessions, bedient die Web-App
- **`elab_workbench/`**: Frontend (React/Vite). Die Benutzeroberfläche des Labs
- **`elab_clients_core/python/`**: Öffentliche Python-Quellen für Clients und gemeinsame Helfer
- **`elab_clients_premium/python/`**: Private/kommerzielle Python-Clients und API-Beispiele
- **`elab_clients_core/esp32/arduino/`**: Öffentliche Arduino-Sketches für ESP32-Ziele
- **`elab_server/`**: Backend-Komponenten (State-Management, Discovery, Recording, Replay)
- **`doc/`**: Installationsanleitungen und ausführliche Dokumentation
- **`tests/`**: Backend- und Integrations-Tests

## 🛠️ Schnelleinstieg

```bash
# Backend
pip install -r requirements.txt
python server.py -d

# Frontend (separates Terminal)
cd elab_workbench
npm install
npm run dev

# Client simulieren (weiteres Terminal)
python elab_clients_core/python/clients/FrequenceCounterClient.py
```

## 📖 Dokumentation

| Dokument | Inhalt |
|----------|--------|
| **[`.github/copilot-instructions.md`](.github/copilot-instructions.md)** | ⭐ **Zentrale KI-Dokumentation** – Architektur, Coding-Guidelines, Agent-Verhalten |
| [`doc/overview.md`](doc/overview.md) | Architektur-Übersicht (Data Provider Pattern) |
| [`doc/api.md`](doc/api.md) | Socket.IO Event-Referenz & Protokoll |
| [`doc/classes.md`](doc/classes.md) | Klassen-Diagramme & Datenstrukturen |
| [`doc/install.md`](doc/install.md) | Vollständige Installations- & Setup-Anleitung |
| [`doc/plugin_development.md`](doc/plugin_development.md) | Entwicklung von Custom-Plugins |
| [`doc/schema_reference.md`](doc/schema_reference.md) | Manifest-Schema & Validierung |
| [`doc/deployment.md`](doc/deployment.md) | Produktion (systemd, nginx/TLS, Backup) |
| [`doc/test.md`](doc/test.md) | Test-Strategie & -Struktur |

## 💡 Wichtig für KI-Agenten

👉 **Alle KI-Agenten sollten [`.github/copilot-instructions.md`](.github/copilot-instructions.md) als primäre Quelle nutzen.**

Diese zentrale Anleitung enthält:

- Vollständige Projekt-Architektur & Richtlinien
- Coding-Standards (Python, JavaScript/React)
- Build & Test Workflow
- Sicherheitsvorkehrungen
- Agent-Verhalten & Best Practices

---

**Schnelle Links:**

- 🔧 [Setup & Tests](doc/install.md)
- 🏗️ [Architektur-Konzept](.github/copilot-instructions.md#-architektur-konzept)
- 📝 [Coding-Richtlinien](.github/copilot-instructions.md#-coding-richtlinien)
- ⚠️ [Häufige Fehler](.github/copilot-instructions.md#-häufige-fehler-vermeiden)
