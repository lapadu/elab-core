import React, { useState, useCallback } from "react";
import { Icons, preventFocusOnMouseDown } from "../utils/Shared";
import { useChannelSources } from "./core/hooks/useChannelSources";
import { useTriggerModel } from "./core/hooks/useTriggerModel";
import ChannelToolbar from "./core/templates/ChannelToolbar";
import { applyDroppedTrigger } from "./core/utils/configUtils";
import { MetricWidget } from "./core/templates/MetricWidget";

// ==========================================
// MAIN WIDGET: measure multi-channel.
// Reuses MetricWidget (tpl_metric) for the actual value display (unit,
// SI-prefix range, decimals) and only adds channel/trigger management
// (ChannelToolbar) and drag'n'drop on top.
// ==========================================
const MeasureWidget = ({ task, isConfigMode, onUpdateTask, streamBuffers }) => {
  const [channelMenuOpen, setChannelMenuOpen] = useState(false);
  const [triggerMenuOpen, setTriggerMenuOpen] = useState(false);
  const [rawCaptureAwaiting, setRawCaptureAwaiting] = useState(false);

  const isPaused = task.config?.isPaused ?? false;
  const showUncertainty = task.config?.showUncertainty ?? false;

  const toggleConfigFlag = useCallback((key, value) => {
    onUpdateTask({ ...task, config: { ...(task.config || {}), [key]: value } });
  }, [task, onUpdateTask]);

  const { sources, addSource, removeSource, updateSourceMeta, reorderSources, handleAction: channelAction } =
    useChannelSources(task, onUpdateTask);

  const {
    triggers, activeTrigger, moveTriggerToChannel,
    activateTrigger, deleteTrigger, addTriggerForChannel,
  } = useTriggerModel(task, onUpdateTask);

  const handleAction = useCallback((source, actionId) => {
    channelAction(source, actionId, (src, id) => {
      // Special handling for RAW capture: clear the buffer and await data.
      if (id !== 'START_RAW') return;
      const sourceId = src.originalId || src.id;
      const buf = streamBuffers?.get(sourceId);
      if (buf) buf.clear();
      setRawCaptureAwaiting(true);
      // One-shot hardware capture; drop the "awaiting" indicator after a
      // grace period instead of polling the buffer for freshness.
      setTimeout(() => setRawCaptureAwaiting(false), 15000);
    });
  }, [channelAction, streamBuffers]);

  const handleDragOver = (e) => {
    e.preventDefault();
    e.stopPropagation();
  };

  const handleDrop = (e) => {
    e.preventDefault();
    e.stopPropagation();
    try {
      const dataStr = e.dataTransfer.getData("task");
      if (!dataStr) return;

      const droppedTask = JSON.parse(dataStr);
      if (droppedTask.id === task.id) return;

      if (droppedTask.type === 'TRIGGER') {
        onUpdateTask(applyDroppedTrigger(task, droppedTask));
        return;
      }

      addSource(droppedTask);
    } catch (error) {
      console.error("Error handling drop in Measure:", error);
    }
  };

  if (sources.length === 0) {
    return (
      <div
        onDragOver={handleDragOver}
        onDrop={handleDrop}
        className="h-full flex items-center justify-center border-2 border-dashed border-slate-700 rounded bg-slate-950/30 hover:border-slate-600 transition-colors"
      >
        <div className="text-center text-slate-500 p-4">
          <Icons.Inbox className="mx-auto mb-2 opacity-50" size={32} />
          <p className="text-xs font-bold uppercase tracking-widest">
            Drop Task Here
          </p>
          <p className="text-[10px] text-slate-600 mt-1">
            Drag a sensor to display its value
          </p>
        </div>
      </div>
    );
  }

  // Config mode reuses MetricWidget's own settings (color, per-channel SI range).
  if (isConfigMode) {
    return <MetricWidget task={task} isConfigMode onUpdateTask={onUpdateTask} streamBuffers={streamBuffers} />;
  }

  return (
    <div
      className="h-full relative bg-slate-900 text-slate-200"
      onDragOver={handleDragOver}
      onDrop={handleDrop}
    >
      <ChannelToolbar
        sources={sources}
        onRemoveSource={removeSource}
        onColorChange={(sourceId, color) => updateSourceMeta(sourceId, "color", color)}
        onAction={handleAction}
        onReorder={reorderSources}
        rawCaptureAwaiting={rawCaptureAwaiting}
        channelMenuOpen={channelMenuOpen}
        onToggleChannelMenu={() => { setChannelMenuOpen(prev => !prev); setTriggerMenuOpen(false); }}
        onCloseChannelMenu={() => setChannelMenuOpen(false)}
        triggers={triggers}
        activeTrigger={activeTrigger}
        triggerMenuOpen={triggerMenuOpen}
        onToggleTriggerMenu={() => { setTriggerMenuOpen(prev => !prev); setChannelMenuOpen(false); }}
        onCloseTriggerMenu={() => setTriggerMenuOpen(false)}
        onActivateTrigger={activateTrigger}
        onMoveTrigger={moveTriggerToChannel}
        onRemoveTrigger={deleteTrigger}
        onAddTriggerForChannel={addTriggerForChannel}
      />
      <div className="absolute top-2 right-2 z-40 flex items-center gap-2">
        <button
          onMouseDown={preventFocusOnMouseDown}
          onClick={() => toggleConfigFlag('isPaused', !isPaused)}
          className={`p-1.5 rounded-full border transition-all ${isPaused
            ? "text-amber-200 bg-amber-900/40 border-amber-500/60"
            : "text-slate-300 bg-slate-900/70 border-slate-700/70 hover:bg-slate-800 hover:text-white"}`}
          title="Pause Anzeige"
        >
          {isPaused ? <Icons.Play size={14} /> : <Icons.Pause size={14} />}
        </button>
        <button
          onMouseDown={preventFocusOnMouseDown}
          onClick={() => toggleConfigFlag('showUncertainty', !showUncertainty)}
          className={`p-1.5 rounded-full border transition-all ${showUncertainty
            ? "text-cyan-200 bg-cyan-900/40 border-cyan-500/60"
            : "text-slate-300 bg-slate-900/70 border-slate-700/70 hover:bg-slate-800 hover:text-white"}`}
          title="Fehlerbereich ein/aus"
        >
          <Icons.Sigma size={14} />
        </button>
      </div>
      <MetricWidget
        task={task}
        isConfigMode={false}
        onUpdateTask={onUpdateTask}
        streamBuffers={streamBuffers}
        isPaused={isPaused}
        showUncertainty={showUncertainty}
      />
    </div>
  );
};

import PluginBuilder from "./core/PluginBuilder";

// ==========================================
// 3. PLUGIN EXPORT
// ==========================================
export const MeasurePlugin = new PluginBuilder("system_measure_v1", "Measure Display", "MEASURE")
    .setRender(MeasureWidget)
    .setCreateTask(() => ({
        id: `measure_${Date.now()}`,
        groupId: "system_measure_v1",
        type: "MEASURE",
        name: "Measure",
        color: "#f59e0b",
        virtual: true,
        inputs: { source: null },
        extraChannels: [],
        config: {
          isPaused: false,
          showUncertainty: false,
        },
        ui: {
          mode: "generic",
          defaultTemplate: "system_measure_v1",
        },
    }))
    .build();

