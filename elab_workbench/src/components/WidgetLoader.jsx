import React, { useState, useEffect, useMemo, useSyncExternalStore, useCallback } from "react";
import * as LucideIcons from "lucide-react";
import { Icons } from "../utils/Shared.jsx";

// Error boundary for remote plugins.
class PluginErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error };
  }

  componentDidCatch(error, errorInfo) {
    console.error("Remote Plugin crashed:", error, errorInfo);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="p-4 flex flex-col items-center justify-center h-full text-center">
          <Icons.AlertTriangle className="text-red-500 mb-2" size={24} />
          <div className="text-red-500 text-xs font-bold uppercase tracking-widest">
            Plugin Crashed
          </div>
          <div className="text-[9px] text-slate-500 mt-1">
            {this.state.error?.message}
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}

// Initialize the global plugin registry.
window.ElabPlugins = window.ElabPlugins || {};

// Global registration function used by remote plugins.
window.registerElabPlugin = (id, componentFactory) => {
  console.log(`🔌 [Loader] Registering plugin: ${id}`);
  try {
    // Execute the factory with React and icons injected as dependencies.
    window.ElabPlugins[id] = componentFactory(React, LucideIcons);
    // Notify listeners that the plugin finished loading.
    window.dispatchEvent(
      new CustomEvent("elab-plugin-loaded", { detail: { id } }),
    );
  } catch (e) {
    console.error(`❌ Error initializing plugin ${id}:`, e);
  }
};

export const RemoteWidgetLoader = ({
  task,
  streamBuffers,
  onUpdateTask,
  isConfigMode,
}) => {
  const { url, componentName, apiVersion, integrity } = task.ui || {};
  const isCompatible = !apiVersion || apiVersion.startsWith("1.");
  const isValidConfig = !!(url && componentName && isCompatible);

  const [error, setError] = useState(!isCompatible ? `Incompatible API Version: ${apiVersion}` : null);
  const [legacyDataStreams, setLegacyDataStreams] = useState({});

  // Validate the plugin URL during render (not in an effect) so we never
  // call setState synchronously inside useEffect.
  const urlValidationError = useMemo(() => {
    if (!url) return null;
    let parsed;
    try {
      parsed = new URL(url, window.location.href);
    } catch {
      return `Invalid plugin URL: ${url}`;
    }
    if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
      return `Refused plugin URL with protocol ${parsed.protocol}`;
    }
    return null;
  }, [url]);

  // Poll stream buffers to provide the legacy dataStreams shape expected by remote plugins.
  useEffect(() => {
    if (!streamBuffers || !isValidConfig || error) return;

    const interval = setInterval(() => {
      const updates = {};
      let hasData = false;
      const taskId = task.id;
      const originalId = task.originalId;

      // Retrieve the matching stream buffer.
      const buffer = originalId ? streamBuffers.get(originalId) : streamBuffers.get(taskId);

      if (buffer) {
        const latest = buffer.getLatest();
        // Build the data shape expected by legacy remote plugins.
        updates[taskId] = {
          value: latest ?? 0,
          timestamp: Date.now(),
        };
        if (originalId) updates[originalId] = updates[taskId];

        hasData = true;
      }

      if (hasData) {
        setLegacyDataStreams(updates);
      }
    }, 50); // 20 FPS

    return () => clearInterval(interval);
  }, [streamBuffers, task.id, task.originalId, isValidConfig, error]);

  // 3. Script loading; only responsible for injecting the script tag.  We
  // no longer update component state here – rendering is driven by the
  // derived `Component` variable and the `revision` counter below.
  useEffect(() => {
    if (!isValidConfig || error || urlValidationError) return;

    // If plugin is already available we don't have to do anything special.
    // The render pass that triggered this effect already read from
    // window.ElabPlugins and will show the component.  No setState required.
    if (window.ElabPlugins[componentName]) {
      return;
    }

    // Inject the script only if it is not already present in the DOM.
    const existingScript = document.querySelector(`script[src="${url}"]`);

    if (!existingScript) {
      console.log(`⏳ [Loader] Loading script: ${url}`);
      const script = document.createElement("script");
      script.src = url;
      script.async = true;
      script.crossOrigin = "anonymous"; // Required for meaningful CORS error handling.

      // SRI: when the manifest provides an integrity hash the browser will
      // refuse to execute a tampered script. Without a hash the script
      // is loaded but trust is left to the dispatcher's allow-list.
      if (typeof integrity === "string" && /^sha(256|384|512)-/.test(integrity)) {
        script.integrity = integrity;
      } else if (integrity) {
        console.warn(`⚠️ Ignoring malformed plugin integrity value: ${integrity}`);
      }

      let timeoutId;

      script.onload = () => {
        clearTimeout(timeoutId);
      };

      script.onerror = () => {
        clearTimeout(timeoutId);
        setError(`Failed to load script: ${url}`);
        console.error(`❌ Script load error: ${url}`);
      };

      timeoutId = setTimeout(() => {
        setError(`Timeout loading script: ${url}`);
        console.error(`❌ Script load timeout: ${url}`);
        script.onerror = null; // Prevent double error
      }, 5000);

      document.body.appendChild(script);
    } else {
      console.log(`ℹ️ [Loader] Script already in DOM: ${url}`);
      // no extra state update necessary; revision effect below will cover it
    }
  }, [url, componentName, isValidConfig, error, urlValidationError, integrity]);

  // --- helper effects & rendering ---

  // 1. Subscribe to external plugin registry (Modern React 18+ way)
  // Replaces the manual revision counter and useEffect
  const Component = useSyncExternalStore(
    useCallback((notify) => {
      const handler = (e) => {
        if (e.detail && e.detail.id === componentName) {
          console.log(`✅ [Loader] Component ${componentName} ready.`);
          notify();
        }
      };
      window.addEventListener("elab-plugin-loaded", handler);
      return () => window.removeEventListener("elab-plugin-loaded", handler);
    }, [componentName]),
    () => window.ElabPlugins?.[componentName] || null
  );

  // --- RENDERING ---

  if (!isValidConfig)
    return <div className="p-4 text-red-400 text-xs">Missing UI Config</div>;
  if (error || urlValidationError)
    return <div className="p-4 text-red-400 text-xs">Load Error: {error || urlValidationError}</div>;

  if (!Component) {
    return (
      <div className="h-full flex flex-col items-center justify-center text-slate-500 bg-slate-900">
        <div className="animate-spin mb-2">
          <Icons.Loader2 size={24} />
        </div>
        <div className="text-xs font-mono">LOADING REMOTE UI...</div>
        <div className="text-[9px] opacity-50 mt-1 font-mono text-center px-2">
          {componentName}
        </div>
        <div className="text-[8px] opacity-30 mt-1 truncate max-w-full px-4">
          {url}
        </div>
      </div>
    );
  }

  // Wrap the external component so plugin crashes stay isolated.
return (
    <PluginErrorBoundary>
      {React.createElement(Component, {
        task,
        dataStreams: legacyDataStreams,
        onUpdateTask,
        isConfigMode,
      })}
    </PluginErrorBoundary>
  );
};
