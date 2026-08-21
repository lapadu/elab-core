import { useCallback, useMemo } from "react";
import {
  getTriggers,
  getActiveTrigger,
  patchTrigger,
  moveTrigger,
  removeTrigger,
  setActiveTrigger,
  upsertTriggerForChannel,
} from "../utils/configUtils";

/**
 * Shared generic trigger CRUD for any widget/provider with channels (Scope,
 * Measure, ...). Wraps the pure config-patch helpers in configUtils and
 * applies them straight to `task.config`.
 */
export const useTriggerModel = (task, onUpdateTask) => {
  const applyPatch = useCallback((patch) => {
    onUpdateTask({ ...task, config: { ...task.config, ...patch } });
  }, [task, onUpdateTask]);

  const triggers = useMemo(() => getTriggers(task), [task]);
  const activeTrigger = useMemo(() => getActiveTrigger(task), [task]);

  const patchTriggerById = useCallback((triggerId, patch) => {
    applyPatch(patchTrigger(task, triggerId, patch));
  }, [task, applyPatch]);

  const moveTriggerToChannel = useCallback((triggerId, channelId) => {
    applyPatch(moveTrigger(task, triggerId, channelId));
  }, [task, applyPatch]);

  const activateTrigger = useCallback((triggerId) => {
    applyPatch(setActiveTrigger(triggerId));
  }, [applyPatch]);

  const deleteTrigger = useCallback((triggerId) => {
    applyPatch(removeTrigger(task, triggerId));
  }, [task, applyPatch]);

  const addTriggerForChannel = useCallback((channelId) => {
    applyPatch(upsertTriggerForChannel(task, channelId, { mode: 'rising', level: 0 }));
  }, [task, applyPatch]);

  return {
    triggers,
    activeTrigger,
    patchTriggerById,
    moveTriggerToChannel,
    activateTrigger,
    deleteTrigger,
    addTriggerForChannel,
  };
};
