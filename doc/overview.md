# Architecture Overview

Here is a detailed block diagram of the E-Lab architecture, created with **Mermaid**. It visualizes the connections between hardware, server, and frontend, as well as the two ways plugins get into the system (Internal vs. Remote Injection).

## Architecture Overview & Plugin Integration

The diagram shows the **"Zero-Config"** process and **"Remote UI Loading"**:

1. **Hardware Clients** automatically find the server via UDP.

2. They register via Socket.IO and send a **Manifest**. For "Smart Devices", this manifest contains a URL to their own UI plugin.

3. The **Frontend** dynamically loads this plugin directly from the hardware client (Cross-Origin Script Loading), which extends the UI at runtime without needing to rebuild the frontend.

``` mermaid
graph TD
    %% Define Styling
    classDef hardware fill:#f9f,stroke:#333,stroke-width:2px,color:black;
    classDef server fill:#bbf,stroke:#333,stroke-width:2px,color:black;
    classDef frontend fill:#bfb,stroke:#333,stroke-width:2px,color:black;
    classDef plugin fill:#ff9,stroke:#d4a017,stroke-width:2px,stroke-dasharray: 5 5,color:black;

    subgraph HardwareLayer ["Hardware Layer (Python)"]
        direction TB
        Client1("📡 FrequenceCounterClient.py<br>(Smart Device)"):::hardware
        ClientWebServer("🌍 Mini WebServer (Flask)<br>Hosts: freq_counter_plugin.js"):::hardware
        Client2("🌡️ TempTestClient.py<br>(Standard Sensor)"):::hardware
        
        Client1 -- "Starts" --> ClientWebServer
    end

    subgraph ServerLayer ["Server Layer (Python)"]
        Dispatcher("🖥️ server.py (Dispatcher)<br>Flask + Socket.IO"):::server
        SessionRec("💾 Session Recorder<br>(SQLite DB)"):::server
        SessionRep("▶️ Session Replayer"):::server
        UDP_Svc("📡 UDP Discovery Service"):::server
        
        Dispatcher <--> SessionRec
        Dispatcher <--> SessionRep
        Dispatcher -.-> UDP_Svc
    end

    subgraph FrontendLayer ["Frontend Layer (Browser / React)"]
        Workbench("💻 elab_workbench (React App)"):::frontend
        
        subgraph PluginSystem ["Plugin Management"]
            Registry["📚 PluginRegistry"]
            Loader["🚀 RemoteWidgetLoader"]
            GlobalScope["🌐 window.ElabPlugins"]
        end
        
        Workbench -- "Uses" --> Registry
        Workbench -- "Uses" --> Loader
    end

    %% Connections
    
    %% 1. Discovery
    UDP_Svc -.->|"1. Broadcast (UDP 5005)"| Client1
    UDP_Svc -.->|"1. Broadcast (UDP 5005)"| Client2
    
    %% 2. Registration & Data
    Client1 <==>|"2. Socket.IO (Manifest + URL)"| Dispatcher
    Client2 <==>|"2. Socket.IO (Manifest + Config)"| Dispatcher
    Dispatcher <==>|"3. Forward Events/Data"| Workbench
    
    %% 3. Plugin Loading Paths
    %% Path A: Internal
    InternalPlugins["📦 Internal Plugins<br>(Voltmeter, Logger)"]:::plugin
    InternalPlugins -->|"Import (Build-Time)"| Registry
    
    %% Path B: Remote Injection (The exciting part!)
    ClientWebServer -.->|"4. HTTP GET (Script URL)"| Loader
    Loader --"5. Inject script"--> GlobalScope
    GlobalScope --"6. registerElabPlugin()"--> Registry
    
    %% Legend Styles
    linkStyle 0,1,2,7,8 stroke-width:2px,fill:none,stroke:blue;
    linkStyle 4,5,6 stroke-width:4px,fill:none,stroke:green;
    linkStyle 10,11,12 stroke-width:2px,fill:none,stroke:orange,stroke-dasharray: 5 5;
```

### Explanation of Component Relationships

1. **Hardware Clients (Python)**

    - **Smart Device (e.g., Frequency Counter):** It is more than just a sensor. It starts its own small web server (`run_web_server` in `FrequenceCounterClient.py`) that serves a JavaScript file (`assets/freq_counter_plugin.js`). In the manifest it sends to the server, the address of this script is specified under `ui.url`.

    - **Standard Sensor (e.g., TempSensor):** Uses standard templates (e.g., `tpl_metric`) that are already built into the frontend. It does not need to host its own code.

2. **Server (Dispatcher)**

    - It acts as a mediator. It does not store the plugins itself, but simply forwards the manifests (including the plugin URLs) to the frontend (`available_providers` event).

3. **Frontend (Workbench)**

    - **Internal Plugins:** Are permanently integrated during compilation (`npm run build`). `PluginRegistry.jsx` collects all files from the `plugins/` folder.

    - **External Plugins (Remote Injection):** The `RemoteWidgetLoader` detects that a device is using `custom` mode. It dynamically creates an HTML `<script>` tag with the URL of the hardware client. The loaded script executes `window.registerElabPlugin` and passes its React code to the frontend.
