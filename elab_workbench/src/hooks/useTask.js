// elab_workbench/src/hooks/useTask.js
import { useCallback } from 'react';
import { useDispatcher } from '../contexts/DispatcherContext.jsx';

export const useTask = (task, onUpdateTask) => {
    const dispatcher = useDispatcher();

    const updateConfig = useCallback((key, value) => {
        const newConfig = { ...task.config, [key]: value };
        onUpdateTask({ ...task, config: newConfig });

        const providerId = `prov_${task.originalId || task.id}`;
        dispatcher.sendControlCommand(providerId, {
            action: 'update_config',
            payload: { [key]: value },
        });
    }, [task, onUpdateTask, dispatcher]);

    const updateMeta = useCallback((sourceId, key, value) => {
        let updatedSource = null;
        let isPrimary = false;
  
        // Distinguish between the primary source and an extra channel.
        if (task.inputs?.source?.id === sourceId) {
          updatedSource = { ...task.inputs.source, [key]: value };
          isPrimary = true;
        } else {
          updatedSource = task.extraChannels?.find((c) => c.id === sourceId);
          if (updatedSource) updatedSource = { ...updatedSource, [key]: value };
        }
  
        if (!updatedSource) return;
  
        // Update local UI state first so the change is reflected immediately.
        const newTask = { ...task };
        if (isPrimary) {
          newTask.inputs = { ...newTask.inputs, source: updatedSource };
        } else {
          newTask.extraChannels = newTask.extraChannels.map((c) =>
            c.id === sourceId ? updatedSource : c,
          );
        }
        onUpdateTask(newTask);
  
        // Alias and colour are persisted by the dispatcher, which forwards them
        // to devices that keep their own configuration.
        const targetId = updatedSource.originalId || updatedSource.id;
        if (key === 'color') dispatcher.setTaskColor(targetId, value);
        else if (key === 'alias') dispatcher.setTaskAlias(targetId, value || null);
        else if (key === 'decimals') dispatcher.setTaskDecimals(targetId, value ?? null);
      }, [task, onUpdateTask, dispatcher]);

    return { updateConfig, updateMeta };
};

