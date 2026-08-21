import { useEffect, useRef } from 'react';
import { useDispatcher } from '../contexts/DispatcherContext.jsx';
import { factoryManager } from '../services/FactoryManager';

export const useFactoryData = (task, plugin) => {
  const dispatcher = useDispatcher();
  const isRegistered = useRef(false);
  const pluginRef     = useRef(plugin);
  const taskType      = task?.type;
  const isVirtual     = task?.virtual === true;
  const isRecorded    = task?.is_recorded === true;
  const taskId        = task?.id;
  const originalId    = task?.originalId;
  const factoryKey    = originalId || taskId;
  const providerId    = `prov_${factoryKey}`;

  useEffect(() => {
    // Stop the factory only when the matching provider actually goes offline.
    const handleOffline = (data) => {
      if (data.provider_id === providerId && task?.ui?.isUiInstance) {
        return;
      }
      if (data.provider_id === providerId) {
        factoryManager.unsubscribe(factoryKey, isRegistered.current);
        isRegistered.current = false;
      }
    };

    // Recorded tasks are flagged virtual as well, but the replayer is their
    // only data source - a live factory would mix simulated data in.
    if (!task || !isVirtual || isRecorded || taskType === 'HARDWARE' || !pluginRef.current) {
      return;
    }

    factoryManager.startFactory(task, pluginRef.current, dispatcher);

    if (!isRegistered.current) {
      const subscriberId = `hook_${taskId}_${Date.now()}`;
      factoryManager.subscribe(factoryKey, subscriberId);
      isRegistered.current = subscriberId;
    }

    dispatcher.socket.on('provider_offline', handleOffline);

    return () => {
      if (dispatcher.socket) {
        dispatcher.socket.off('provider_offline', handleOffline);
      }
      if (isRegistered.current) {
        factoryManager.unsubscribe(factoryKey, isRegistered.current);
        isRegistered.current = false;
      }
    };
// Keep the dependency list limited to IDs and shallow values.
// eslint-disable-next-line react-hooks/exhaustive-deps
  }, [factoryKey, providerId, task?.ui?.isUiInstance, dispatcher]);

  return null;
};
