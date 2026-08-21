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

## Codebase Memory MCP

**MANDATORY: use Codebase Memory MCP graph tools FIRST — before reading files or making code changes.**

This rule applies to every request involving this codebase.

Always call `list_projects` first when you do not already know the project name, then use the `display_name` or exact `name` returned by that tool.

```json
// Step 0 — discover project names
mcp_codebase-memo_list_projects()

// Step 1 — use the project identifier returned above
mcp_codebase-memo_get_architecture({ "project": "<display_name>" })
```

### Workflow

1. Call `list_projects` to discover the correct project name.
2. Call `get_architecture(project)` to understand the codebase structure.
3. Use `search_graph` to find relevant symbols, `trace_path` for call chains.
4. Use `get_code_snippet` to read specific function implementations.
5. Call `check_index_coverage` to validate candidate paths before exhaustive or negative claims.
6. Only use `read_file` when you need exact raw content to edit a specific line.

### Available Tools (15 MCP tools)

**Indexing:**
- `index_repository(repo_path)` — Index a repository into the knowledge graph
- `list_projects` — List all indexed projects with node/edge counts
- `delete_project(project)` — Remove a project and all its graph data
- `index_status(project)` — Check indexing status

**Querying:**
- `search_graph(name_pattern, name_scope, label, file_pattern, exclude_file_pattern)` — Structured search by label, name/qualified_name, include/exclude file globs
- `trace_path(function_name, direction, depth)` — BFS call chain traversal (direction: inbound/outbound)
- `detect_changes(project)` — Map git diff to affected symbols + risk
- `query_graph(query)` — Execute Cypher-like graph queries (read-only)
- `get_graph_schema(project)` — Node/edge counts, relationship patterns
- `get_code_snippet(qualified_name)` — Read source code for a function
- `get_architecture(project)` — Codebase overview: languages, packages, routes, hotspots
- `search_code(pattern, project)` — Grep-like text search within indexed files
- `check_index_coverage(paths)` — Validate candidate paths and report missed/stale ranges
- `manage_adr(action)` — CRUD for Architecture Decision Records
- `ingest_traces(traces)` — Ingest runtime traces to validate HTTP edges
