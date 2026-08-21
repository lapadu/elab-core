// elab_workbench/src/hooks/useDispatcherSubscription.js
import { useState, useEffect, useRef, useCallback } from 'react';
import dispatcher from '../services/DispatcherClient';
import { StreamBuffer } from '../utils/StreamingUtils';
import { APP_EVENTS } from '../utils/EventTypes';
import { validateManifest, formatManifestErrors } from '../plugins/core/manifestValidator';
import { isReplayId, toReplayId } from '../utils/replayStreams';

export const useDispatcherSubscription = (serverUrl) => {
  const [isConnected, setIsConnected] = useState(false);
  const [sessionState, setSessionState] = useState({ recording: false, sessionId: null });
  const [providers, setProviders] = useState([]);
  const [offlineProviders, setOfflineProviders] = useState(new Set());
  const [availableScripts, setAvailableScripts] = useState([]);
  const [pendingDevices, setPendingDevices] = useState([]);
  const [streamBuffers] = useState(() => new Map());

  const providerUpdateTimeout = useRef(null);

  const clearStreamBuffers = useCallback((bufferIds = null) => {
    if (bufferIds && Array.isArray(bufferIds)) {
      bufferIds.forEach(id => {
        if (streamBuffers.has(id)) {
          streamBuffers.get(id).clear();
        }
      });
    } else {
      // Clear all buffers if no specific IDs are provided.
      streamBuffers.forEach(buffer => buffer.clear());
    }
  }, [streamBuffers]);

  useEffect(() => {
    dispatcher.connect(serverUrl);

    const handleConnect = () => setIsConnected(true);
    const handleDisconnect = () => setIsConnected(false);
    const handleSession = (status) => setSessionState(status);
    const handleScripts = (scripts) => setAvailableScripts(scripts);
    const handlePending = (list) => setPendingDevices(Array.isArray(list) ? list : []);

    const handleProviders = (newProviders) => {
      if (providerUpdateTimeout.current) clearTimeout(providerUpdateTimeout.current);
      providerUpdateTimeout.current = setTimeout(() => {
        // Soft-validate manifests: keep all, but log violations so a buggy or
        // hostile provider is visible in the dev console. Hard-rejecting was
        // considered, but legitimate edge cases (e.g. recorded-session
        // providers, future capability extensions) make a strict gate too
        // brittle right now.
        for (const p of newProviders || []) {
          const { ok, errors } = validateManifest(p);
          if (!ok) {
            console.warn(
              `⚠️ Manifest schema violation from provider ${p?.id ?? '<unknown>'}: ${formatManifestErrors(errors)}`,
            );
          }
        }
        // Shallow-compare against the previous list to avoid creating a new
        // array identity (and re-triggering every downstream useMemo) when
        // the dispatcher re-emits an unchanged provider list.
        setProviders((prev) => {
          const next = Array.isArray(newProviders) ? newProviders : [];
          if (Array.isArray(prev) && prev.length === next.length) {
            let changed = false;
            for (let i = 0; i < next.length; i += 1) {
              if (prev[i] !== next[i]) { changed = true; break; }
            }
            if (!changed) return prev;
          }
          return next;
        });
        setOfflineProviders(prev => {
          const next = new Set(prev);
          let mutated = false;
          (newProviders || []).forEach(p => {
            if (next.has(p.id)) { next.delete(p.id); mutated = true; }
          });
          return mutated ? next : prev;
        });
      }, 200);
    };

    const handleProviderOffline = (data) => {
      setOfflineProviders(prev => {
        const next = new Set(prev);
        next.add(data.provider_id);
        return next;
      });
    };

    const handleTaskConfigChanged = (data) => {
      const { task_id, changes } = data;
      if (!task_id || !changes) return;
      setProviders((prev) => {
        if (!Array.isArray(prev)) return prev;
        return prev.map((p) => {
          let updated = false;
          const updatedTasks = (p.tasks || []).map((t) => {
            if (t.id === task_id) {
              updated = true;
              return { ...t, ...changes };
            }
            return t;
          });
          if (updated) {
            return { ...p, tasks: updatedTasks };
          }
          return p;
        });
      });
    };

    const handleStream = (streamData) => {
      const rawId = streamData.sourceId;
      if (!rawId) return;
      // Hard separation between a recording and its live source: replay
      // samples only ever land in a "rec_" buffer, live samples never do.
      const isReplay = streamData._is_replay === true;
      const id = isReplay ? toReplayId(rawId) : rawId;
      if (!isReplay && isReplayId(id)) return;
      if (!streamBuffers.has(id)) {
        // Cap memory: 60 000 points OR last 5 minutes, whichever hits first.
        // 5 min @ 1 kHz = 300k points -> point cap kicks in; for low-rate
        // sensors the time window keeps history light.
        streamBuffers.set(id, new StreamBuffer(60000, 5 * 60 * 1000));
      }
      streamBuffers.get(id).push(streamData);
    };

    // A replay position jump (stop / seek / rewind on play) invalidates every
    // buffered replay sample, so flush them before the new segment arrives.
    const handleReplayReset = () => {
      streamBuffers.forEach((buffer, id) => {
        if (isReplayId(id)) buffer.clear();
      });
    };
    
    // Register handlers through the shared event constants.
    dispatcher.on(APP_EVENTS.ON_CONNECTION_ESTABLISHED, handleConnect);
    dispatcher.on(APP_EVENTS.ON_DISCONNECT, handleDisconnect);
    dispatcher.on(APP_EVENTS.ON_PROVIDER_UPDATE, handleProviders);
    dispatcher.on(APP_EVENTS.ON_PROVIDER_OFFLINE, handleProviderOffline);
    dispatcher.on(APP_EVENTS.ON_TASK_CONFIG_CHANGED, handleTaskConfigChanged);
    dispatcher.on(APP_EVENTS.ON_DATA_STREAM, handleStream);
    dispatcher.on(APP_EVENTS.ON_REPLAY_RESET, handleReplayReset);
    dispatcher.on(APP_EVENTS.ON_SESSION_STATUS, handleSession);
    dispatcher.on(APP_EVENTS.ON_SCRIPTS_UPDATE, handleScripts);
    dispatcher.on(APP_EVENTS.ON_PENDING_DEVICES, handlePending);

    return () => {
      dispatcher.off(APP_EVENTS.ON_CONNECTION_ESTABLISHED, handleConnect);
      dispatcher.off(APP_EVENTS.ON_DISCONNECT, handleDisconnect);
      dispatcher.off(APP_EVENTS.ON_PROVIDER_UPDATE, handleProviders);
      dispatcher.off(APP_EVENTS.ON_PROVIDER_OFFLINE, handleProviderOffline);
      dispatcher.off(APP_EVENTS.ON_TASK_CONFIG_CHANGED, handleTaskConfigChanged);
      dispatcher.off(APP_EVENTS.ON_DATA_STREAM, handleStream);
      dispatcher.off(APP_EVENTS.ON_REPLAY_RESET, handleReplayReset);
      dispatcher.off(APP_EVENTS.ON_SESSION_STATUS, handleSession);
      dispatcher.off(APP_EVENTS.ON_SCRIPTS_UPDATE, handleScripts);
      dispatcher.off(APP_EVENTS.ON_PENDING_DEVICES, handlePending);
      
      dispatcher.disconnect();
    };
  }, [serverUrl, streamBuffers]); // ESLint intentionally ignores clearStreamBuffers because it doesn't hold reactive state here.

  return {
    isConnected,
    sessionState,
    streamBuffers,
    providers,
    offlineProviders,
    availableScripts,
    pendingDevices,
    clearStreamBuffers,
    // Delegate directly to the dispatcher helpers.
    startScript: (filename) => dispatcher.startClientScript(filename),
    stopScript: (filename) => dispatcher.stopClientScript(filename),
    approvePendingDevice: (deviceId, manifestHash) =>
      dispatcher.approvePendingDevice(deviceId, manifestHash),
    revokeDevice: (deviceId) => dispatcher.revokeDevice(deviceId),
    deleteDeviceCredential: (deviceId) =>
      dispatcher.deleteDeviceCredential(deviceId),
  };
};