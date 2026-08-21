import { useCallback, useMemo } from "react";
import dispatcher from "../../../services/DispatcherClient";

/**
 * Shared multi-channel source management (primary + extra channels) for any
 * widget that lets the user drop several data sources onto one instrument
 * (Scope, Measure, ...). Handles dedup, add/remove, per-channel meta updates
 * (name/color), and drag'n'drop layer reordering (list order = channel-menu
 * / draw-priority order).
 */
export const useChannelSources = (task, onUpdateTask, { singleSource = false } = {}) => {
  const sources = useMemo(() => {
    // In single-source mode, use only the task's own stream as input.
    if (singleSource) {
      return [{
        id: task.originalId || task.id,
        name: task.name,
        color: task.color,
        config: task.config,
        providerId: task.providerId,
        originalId: task.originalId,
        actions: task.actions || [],
      }];
    }
    const s = [];
    if (task.inputs?.source) s.push(task.inputs.source);
    if (task.extraChannels) s.push(...task.extraChannels);
    // Ensure unique sources by ID (avoid duplicate rendering / ghost traces)
    return Array.from(new Map(s.map((src) => [src?.id, src])).values());
  }, [task, singleSource]);

  const addSource = useCallback((droppedTask) => {
    if (droppedTask.id === task.id || sources.find((s) => s.id === droppedTask.id)) return;
    const newInputs = !task.inputs?.source ? { ...task.inputs, source: droppedTask } : task.inputs;
    const newExtra = task.inputs?.source ? [...(task.extraChannels || []), droppedTask] : (task.extraChannels || []);
    onUpdateTask({ ...task, inputs: newInputs, extraChannels: newExtra });
  }, [task, sources, onUpdateTask]);

  const removeSource = useCallback((sourceId) => {
    const newInputs = task.inputs?.source?.id === sourceId ? { ...task.inputs, source: null } : task.inputs;
    const newExtra = (task.extraChannels || []).filter((c) => c.id !== sourceId);
    onUpdateTask({ ...task, inputs: newInputs, extraChannels: newExtra });
  }, [task, onUpdateTask]);

  const updateSourceMeta = useCallback((sourceId, key, value) => {
    // In single-source mode the task itself is the source.
    if (singleSource) {
      onUpdateTask({ ...task, [key]: value });
      const targetProvider = task.providerId || task.originalId || task.id;
      dispatcher.sendControlCommand(`prov_${targetProvider}`, {
        action: "update_meta", payload: { [key]: value },
      });
      return;
    }

    const isPrimary = task.inputs?.source?.id === sourceId;
    let updatedSource;
    if (isPrimary) {
      updatedSource = { ...task.inputs.source, [key]: value };
    } else {
      const source = task.extraChannels?.find((c) => c.id === sourceId);
      if (source) updatedSource = { ...source, [key]: value };
    }
    if (!updatedSource) return;

    const newInputs = isPrimary ? { ...task.inputs, source: updatedSource } : task.inputs;
    const newExtra = isPrimary ? task.extraChannels : task.extraChannels.map((c) => (c.id === sourceId ? updatedSource : c));
    onUpdateTask({ ...task, inputs: newInputs, extraChannels: newExtra });

    dispatcher.sendControlCommand(`prov_${updatedSource.originalId || updatedSource.id}`, {
      action: "update_meta", payload: { [key]: value },
    });
  }, [task, onUpdateTask, singleSource]);

  // Reorder channels (drag'n'drop in ChannelMenu). List order = layer order:
  // the first entry becomes the primary source, the rest the extra channels.
  const reorderSources = useCallback((orderedIds) => {
    if (singleSource) return;
    const byId = new Map(sources.map((s) => [s.id, s]));
    const ordered = orderedIds.map((id) => byId.get(id)).filter(Boolean);
    if (ordered.length === 0) return;
    const [primary, ...rest] = ordered;
    onUpdateTask({ ...task, inputs: { ...task.inputs, source: primary }, extraChannels: rest });
  }, [sources, task, onUpdateTask, singleSource]);

  // Special sensor actions declared in the manifest (e.g. the ESP32
  // voltmeter's RAW capture button), forwarded to the provider as a control
  // command. `onSpecialAction` lets the caller react locally (e.g. clear a
  // buffer, show a "capturing" overlay) before the command is dispatched.
  const handleAction = useCallback((source, actionId, onSpecialAction) => {
    if (!source) return;
    onSpecialAction?.(source, actionId);
    const providerId = source.config?.providerId || source.providerId;
    const target = providerId || `prov_${source.originalId || source.id}`;
    dispatcher.sendControlCommand(target, { action: actionId });
  }, []);

  return { sources, addSource, removeSource, updateSourceMeta, reorderSources, handleAction };
};
