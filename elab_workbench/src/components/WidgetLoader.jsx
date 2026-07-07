import React, { useState, useEffect, useMemo, useSyncExternalStore, useCallback } from "react";
import * as LucideIcons from "lucide-react";
import { Icons } from "../utils/Shared.jsx";

// ---------------------------------------------------------------------------
// Plugin registry sandbox.
//
// Plugins are still registered through ``window.registerElabPlugin`` so existing
// remote bundles keep working, but the underlying storage is now an isolated
// ``Map`` we control. We freeze the React/Icons we hand to the factory, refuse
// silent overrides of an already-registered id, and isolate factory crashes.
// ---------------------------------------------------------------------------
const _pluginRegistry = new Map();
const _pluginListeners = new Set();

function _notifyPluginChange(id) {
  try {
    window.dispatchEvent(new CustomEvent("elab-plugin-loaded", { detail: { id } }));
  } catch { /* ignore */ }
  for (const fn of _pluginListeners) {
    try { fn(id); } catch { /* ignore */ }
  }
}

const _SafeReact = Object.freeze({ ...React });
const _SafeIcons = Object.freeze({ ...LucideIcons });

function _registerPlugin(id, componentFactory) {
  if (typeof id !== "string" || !id) {
    console.warn("⚠️ registerElabPlugin: refused plugin without id");
    return;
  }
  if (typeof componentFactory !== "function") {
    console.warn(`⚠️ registerElabPlugin: factory for ${id} is not a function`);
    return;
  }
  if (_pluginRegistry.has(id)) {
    console.warn(`⚠️ registerElabPlugin: plugin ${id} already registered – ignoring duplicate`);
    return;
  }
  console.log(`🔌 [Loader] Registering plugin: ${id}`);
  try {
    const component = componentFactory(_SafeReact, _SafeIcons);
    if (!component) {
      console.warn(`⚠️ Plugin ${id} factory returned no component`);
      return;
    }
    _pluginRegistry.set(id, component);
    _notifyPluginChange(id);
  } catch (e) {
    console.error(`❌ Error initializing plugin ${id}:`, e);
  }
}

// Expose a read-only view on ``window.ElabPlugins`` so legacy lookups keep
// working, but writes have to go through ``registerElabPlugin``.
if (typeof window !== "undefined") {
  try {
    Object.defineProperty(window, "ElabPlugins", {
      configurable: false,
      enumerable: true,
      get() {
        return new Proxy(_pluginRegistry, {
          get(target, prop) {
            if (typeof prop === "string" && target.has(prop)) return target.get(prop);
            return undefined;
          },
          set() {
            console.warn("window.ElabPlugins is read-only; use registerElabPlugin");
            return true;
          },
          has(target, prop) {
            return typeof prop === "string" && target.has(prop);
          },
        });
      },
    });
  } catch {
    // Older runtimes that already pinned ElabPlugins – fall back to a plain
    // object so the loader keeps working.
    window.ElabPlugins = window.ElabPlugins || {};
  }
  window.registerElabPlugin = _registerPlugin;
}

// ---------------------------------------------------------------------------
// Origin allow-list (mirrors the dispatcher's ELAB_PLUGIN_ORIGINS env var).
// The list is populated by DispatcherClient on ``connection_established``.
// Same-origin URLs (workbench host) are always allowed.
// ---------------------------------------------------------------------------
function _isPluginUrlAllowed(parsed) {
  if (!parsed) return false;
  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") return false;
  try {
    if (parsed.origin && parsed.origin === window.location.origin) return true;
    const serverOrigin = (typeof window !== "undefined" && window.__ELAB_SERVER_ORIGIN__) || null;
    if (serverOrigin && parsed.origin === serverOrigin) return true;
    const list = (typeof window !== "undefined" && Array.isArray(window.__ELAB_PLUGIN_ORIGINS__))
      ? window.__ELAB_PLUGIN_ORIGINS__
      : null;
    if (!list || list.length === 0) {
      // Before the dispatcher has spoken we restrict to same-origin only.
      return false;
    }
    const urlOrigin = parsed.origin.toLowerCase();
    return list.some((pattern) => {
      if (pattern.endsWith("*")) {
        return urlOrigin.startsWith(pattern.slice(0, -1));
      }
      return urlOrigin === pattern;
    });
  } catch {
    return false;
  }
}

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

// Initialize the global plugin registry. The actual storage and the
// ``window.registerElabPlugin`` bridge live at the top of this module so the
// sandbox is installed before any plugin can call it.

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
    if (!_isPluginUrlAllowed(parsed)) {
      return `Refused plugin URL outside allow-list: ${parsed.origin}`;
    }
    return null;
  }, [url]);

  // Collect every id this widget cares about: its own task (for SENSOR-style
  // remote plugins that visualise their own stream) plus any source(s) that
  // were dropped onto it (MEASURE-style consumers reading
  // `task.inputs.source` + `task.extraChannels[]`).
  const referencedIds = useMemo(() => {
    const ids = new Set();
    if (task?.id) ids.add(task.id);
    if (task?.originalId) ids.add(task.originalId);
    const src = task?.inputs?.source;
    if (src?.id) ids.add(src.id);
    if (src?.originalId) ids.add(src.originalId);
    const extras = Array.isArray(task?.extraChannels) ? task.extraChannels : [];
    for (const c of extras) {
      if (!c) continue;
      if (c.id) ids.add(c.id);
      if (c.originalId) ids.add(c.originalId);
    }
    return Array.from(ids);
  }, [task]);

  // Poll stream buffers to provide the legacy dataStreams shape expected by remote plugins.
  useEffect(() => {
    if (!streamBuffers || !isValidConfig || error) return;

    const interval = setInterval(() => {
      const updates = {};
      let hasData = false;
      const now = Date.now();

      for (const id of referencedIds) {
        const buffer = streamBuffers.get(id);
        if (!buffer) continue;
        // Expose both the latest scalar (legacy SENSOR plugins) and the
        // StreamBuffer itself (MEASURE plugins that need raw sample history).
        updates[id] = {
          value: buffer.getLatest?.() ?? 0,
          timestamp: now,
          buffer,
        };
        hasData = true;
      }

      if (hasData) {
        setLegacyDataStreams(updates);
      }
    }, 50); // 20 FPS

    return () => clearInterval(interval);
  }, [streamBuffers, referencedIds, isValidConfig, error]);

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
