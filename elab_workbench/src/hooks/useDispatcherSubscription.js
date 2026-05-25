// elab_workbench/src/hooks/useDispatcherSubscription.js
import { useState, useEffect, useRef, useCallback } from 'react';
import dispatcher from '../services/DispatcherClient';
import { StreamBuffer } from '../utils/StreamingUtils';
import { APP_EVENTS } from '../utils/EventTypes';
import { validateManifest, formatManifestErrors } from '../plugins/core/manifestValidator';

export const useDispatcherSubscription = (serverUrl) => {
  const [isConnected, setIsConnected] = useState(false);
  const [sessionState, setSessionState] = useState({ recording: false, sessionId: null });
  const [providers, setProviders] = useState([]);
  const [offlineProviders, setOfflineProviders] = useState(new Set());
  const [availableScripts, setAvailableScripts] = useState([]);
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
        setProviders(newProviders);
        setOfflineProviders(prev => {
          const next = new Set(prev);
          newProviders.forEach(p => {
            if (next.has(p.id)) next.delete(p.id);
          });
          return next;
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

    const handleStream = (streamData) => {
      const id = streamData.sourceId;
      if (!id) return;
      if (!streamBuffers.has(id)) {
        // Cap memory: 60 000 points OR last 5 minutes, whichever hits first.
        // 5 min @ 1 kHz = 300k points -> point cap kicks in; for low-rate
        // sensors the time window keeps history light.
        streamBuffers.set(id, new StreamBuffer(60000, 5 * 60 * 1000));
      }
      streamBuffers.get(id).push(streamData);
    };
    
    // Register handlers through the shared event constants.
    dispatcher.on(APP_EVENTS.ON_CONNECTION_ESTABLISHED, handleConnect);
    dispatcher.on(APP_EVENTS.ON_DISCONNECT, handleDisconnect);
    dispatcher.on(APP_EVENTS.ON_PROVIDER_UPDATE, handleProviders);
    dispatcher.on(APP_EVENTS.ON_PROVIDER_OFFLINE, handleProviderOffline);
    dispatcher.on(APP_EVENTS.ON_DATA_STREAM, handleStream);
    dispatcher.on(APP_EVENTS.ON_SESSION_STATUS, handleSession);
    dispatcher.on(APP_EVENTS.ON_SCRIPTS_UPDATE, handleScripts);

    return () => {
      dispatcher.off(APP_EVENTS.ON_CONNECTION_ESTABLISHED, handleConnect);
      dispatcher.off(APP_EVENTS.ON_DISCONNECT, handleDisconnect);
      dispatcher.off(APP_EVENTS.ON_PROVIDER_UPDATE, handleProviders);
      dispatcher.off(APP_EVENTS.ON_PROVIDER_OFFLINE, handleProviderOffline);
      dispatcher.off(APP_EVENTS.ON_DATA_STREAM, handleStream);
      dispatcher.off(APP_EVENTS.ON_SESSION_STATUS, handleSession);
      dispatcher.off(APP_EVENTS.ON_SCRIPTS_UPDATE, handleScripts);
      
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
    clearStreamBuffers,
    // Delegate directly to the dispatcher helpers.
    startScript: (filename) => dispatcher.startClientScript(filename),
    stopScript: (filename) => dispatcher.stopClientScript(filename),
  };
};