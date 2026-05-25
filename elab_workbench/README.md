# E-Lab Workbench

The E-Lab Workbench is the React-based frontend for the E-Lab distributed measurement platform. It connects to the dispatcher backend over Socket.IO and renders live sensors, generators, math nodes, and custom plugin UIs.

## Features

- Real-time measurement visualization via WebSockets
- Dynamic plugin/widget loading based on provider manifests
- Zero-config workflow with UDP-discovered providers
- Built-in views for metric, scope, and spectrum-style tasks
- Modern frontend stack with React, Vite, and Tailwind CSS

## Project Context

This frontend is part of a larger repository:

- `server.py`: central dispatcher backend
- `elab_server/`: backend modules (state, discovery, process manager, recorder)
- `elab_clients_core/python/`: public Python client implementations and shared helpers
- `elab_clients_core/esp32/arduino/`: public ESP32 sketches
- `doc/`: architecture and API documentation

## Prerequisites

- Node.js 20+
- npm
- Python 3.10+ (required for backend and client scripts)

## Development

Start the workbench in development mode:

```bash
cd elab_workbench
npm install
npm run dev
```

Open <http://localhost:5173>.

## Production Build

Build the frontend bundle:

```bash
cd elab_workbench
npm run build
```

The backend serves the built app when available.

## Recommended Local Workflow

Run these in separate terminals:

1. Start dispatcher backend

```bash
python server.py
```

1. Start frontend dev server

```bash
cd elab_workbench
npm run dev
```

1. Start one or more example clients

```bash
python elab_clients_core/python/clients/TempTestClient.py
python elab_clients_core/python/clients/FrequenceCounterClient.py
```

1. Optional: start core API example node

```bash
python elab_clients_core/python/api/fir_filter_node.py
```

## Scripts

- `npm run dev`: start Vite dev server
- `npm run build`: build production bundle
- `npm run preview`: preview production build locally
- `npm run lint`: run ESLint
- `npm test`: run Vitest once
- `npm run test:watch`: run Vitest in watch mode
- `npm run test:coverage`: run tests with coverage
- `npm run format`: format source files with Prettier
- `npm run format:check`: check formatting
- `npm run generate-types`: generate manifest TypeScript types from schema

## Architecture Notes

- The workbench does not poll sensors directly; it consumes routed streams from the dispatcher.
- Providers keep streaming data even when no widget is visible; UI subscriptions only control forwarding to clients.
- Remote plugin URLs should be validated and integrity-protected as described in the plugin security docs.

## Testing and Quality

From `elab_workbench/`:

```bash
npm run lint
npm test
```

For full project checks, run backend tests from repository root as well.

## Related Documentation

- `doc/overview.md`
- `doc/api.md`
- `doc/plugin_development.md`
- `doc/schema_reference.md`
- `doc/test.md`
