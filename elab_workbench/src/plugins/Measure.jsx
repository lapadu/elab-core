/* eslint-disable react-refresh/only-export-components */
import React, { useState, useEffect, useRef } from "react";
import { Icons, COLOR_PALETTE } from "../utils/Shared";

// ==========================================
// 1. SUBCOMPONENT: single live-data channel.
// ==========================================
const ChannelDisplay = ({ source, streamBuffers, showUncertainty, pausedSample = null }) => {
  // Recorded tasks must not fall back to live data via originalId.
  const buffer = source.is_recorded
    ? streamBuffers?.get(source.id)
    : (streamBuffers?.get(source.id) || streamBuffers?.get(source.originalId));
  const liveRawValue = buffer?.getLatest?.();
  const latestPoint = buffer?.last?.();
  const liveUncertainty = latestPoint?.u || buffer?.getLatestUncertainty?.() || null;
  const rawValue = pausedSample?.value ?? liveRawValue;
  const uncertainty = pausedSample?.uncertainty ?? liveUncertainty;

  const config = source.config || {};
  const factor = config.factor !== undefined ? config.factor : 1.0;

  // Format the displayed value.
  const displayValue =
    rawValue !== null && rawValue !== undefined
      ? (rawValue * factor).toFixed(2)
      : "---";

  const uncertaintyDelta = (() => {
    if (!showUncertainty || rawValue === null || rawValue === undefined || !uncertainty) return null;
    const systematic = Number(uncertainty.systematicAbs);
    const randomSigma = Number(uncertainty.randomSigma);
    const confidenceK = Number(uncertainty.confidenceK);
    const k = Number.isFinite(confidenceK) ? Math.abs(confidenceK) : 2;
    const delta =
      (Number.isFinite(systematic) ? Math.abs(systematic) : 0) +
      (Number.isFinite(randomSigma) ? Math.abs(randomSigma) * k : 0);
    if (!Number.isFinite(delta) || delta <= 0) return null;
    return delta * factor;
  })();

  const unit = source.unit || config.unit || "";
  const intervalText = (() => {
    if (!showUncertainty || uncertaintyDelta === null || rawValue === null || rawValue === undefined) return null;
    const center = rawValue * factor;
    const high = center + uncertaintyDelta;
    const low = center - uncertaintyDelta;
    return `${center.toFixed(3)} [+${high.toFixed(3)} -${low.toFixed(3)}]`;
  })();

  return (
    <div className="flex flex-col items-center justify-center p-3 border-b border-slate-800/50 last:border-0 w-full">
      <div className="text-[10px] text-slate-500 uppercase tracking-widest font-bold mb-1 flex items-center gap-2">
        <div
          className="w-2 h-2 rounded-full"
          style={{ backgroundColor: source.color }}
        ></div>
        {source.name}
      </div>
      <div
        className="text-4xl font-mono font-bold drop-shadow-lg"
        style={{ color: source.color }}
      >
        {displayValue}
        <span className="text-lg text-slate-600 ml-1">{unit}</span>
      </div>
      {showUncertainty && uncertaintyDelta !== null && rawValue !== null && rawValue !== undefined && (
        <>
          <div className="mt-1 text-[11px] text-slate-400 font-mono">
            ±{uncertaintyDelta.toFixed(3)} {unit}
          </div>
          {intervalText && (
            <div className="mt-0.5 text-[10px] text-slate-500 font-mono">
              {intervalText} {unit}
            </div>
          )}
        </>
      )}
    </div>
  );
};

import GenericPluginWidget from "../components/GenericPluginWidget";

import { useTask } from "../hooks/useTask";

// ==========================================
// 2. MAIN WIDGET: measure multi-channel.
// ==========================================
const MeasureWidget = ({ task, isConfigMode, onUpdateTask, streamBuffers }) => {
  const { updateMeta } = useTask(task, onUpdateTask);
  const showUncertainty = task.config?.showUncertainty ?? false;
  const isPaused = task.config?.isPaused ?? false;
  const [pausedSnapshot, setPausedSnapshot] = useState({});

  const getSourceReading = (source) => {
    const buffer = source?.is_recorded
      ? streamBuffers?.get(source.id)
      : (streamBuffers?.get(source.id) || streamBuffers?.get(source.originalId));
    const value = buffer?.getLatest?.();
    const point = buffer?.last?.();
    const uncertainty = point?.u || buffer?.getLatestUncertainty?.() || null;
    return { value, uncertainty };
  };

  const toggleUncertainty = () => {
    onUpdateTask({
      ...task,
      config: { ...(task.config || {}), showUncertainty: !showUncertainty },
    });
  };

  const togglePause = () => {
    const nextPaused = !isPaused;
    if (nextPaused) {
      const snapshot = {};
      sources.forEach((s) => {
        snapshot[s.id] = getSourceReading(s);
      });
      setPausedSnapshot(snapshot);
    } else {
      setPausedSnapshot({});
    }
    onUpdateTask({
      ...task,
      config: { ...(task.config || {}), isPaused: nextPaused },
    });
  };
  
  // Drive re-renders from the browser render loop.
  const requestRef = useRef();
  const [, setTick] = useState(0);

  useEffect(() => {
    // Sync updates with the browser render cycle.
    const update = () => {
      setTick(t => t + 1);
      requestRef.current = requestAnimationFrame(update);
    };
    
    // Start the loop.
    requestRef.current = requestAnimationFrame(update);
    
    // Clean up on unmount.
    return () => cancelAnimationFrame(requestRef.current);
  }, []);

  // Combine the primary source and all extra channels.
  const sources = [];
  if (task.inputs?.source) sources.push(task.inputs.source);
  if (task.extraChannels) sources.push(...task.extraChannels);

  // --- DRAG AND DROP FOR EMPTY WIDGETS ---
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

      // Use the first dropped task as the primary source.
      if (!task.inputs?.source) {
        onUpdateTask({ ...task, inputs: { source: droppedTask } });
      } else {
        // Otherwise append it as an extra channel.
        const extra = task.extraChannels || [];
        if (!extra.find((c) => c.id === droppedTask.id)) {
          onUpdateTask({ ...task, extraChannels: [...extra, droppedTask] });
        }
      }
    } catch (error) {
      console.error("Error handling drop in Measure:", error);
    }
  };

  // --- REMOVE CHANNEL ---
  const removeSource = (sourceId) => {
    const newTask = { ...task };
    if (task.inputs?.source?.id === sourceId) {
      newTask.inputs = { ...newTask.inputs, source: null };
    } else {
      newTask.extraChannels = (newTask.extraChannels || []).filter(
        (c) => c.id !== sourceId,
      );
    }
    onUpdateTask(newTask);
  };

  const configContent = (
    <div className="space-y-3">
      <div className="bg-slate-950 p-3 rounded-lg border border-slate-800">
        <label className="flex items-center justify-between text-xs text-slate-300 cursor-pointer">
          <span className="font-bold uppercase tracking-wider">Fehlerbereich anzeigen</span>
          <input
            type="checkbox"
            checked={showUncertainty}
            onChange={(e) => onUpdateTask({
              ...task,
              config: { ...(task.config || {}), showUncertainty: e.target.checked },
            })}
            className="accent-cyan-500"
          />
        </label>
        <p className="text-[10px] text-slate-500 mt-2">Nutzt uncertainty aus dem Datenstrom, wenn vorhanden.</p>
      </div>

      {sources.map((s) => (
        <div
          key={s.id}
          className="bg-slate-950 p-3 rounded-lg border border-slate-800"
        >
          {/* Name input and remove button */}
          <div className="flex justify-between items-center mb-3">
            <input
              type="text"
              value={s.name}
              onChange={(e) =>
                updateMeta(s.id, "name", e.target.value)
              }
              className="bg-slate-900 text-xs font-bold text-slate-300 px-2 py-1 rounded border border-slate-700 w-2/3 focus:outline-none focus:border-blue-500"
            />
            <button
              onClick={() => removeSource(s.id)}
              className="text-slate-500 hover:text-red-400 hover:bg-red-900/30 p-1.5 rounded transition-colors"
              title="Remove Channel"
            >
              <Icons.Trash2 size={14} />
            </button>
          </div>

          {/* Color Picker für diesen spezifischen Kanal */}
          <div className="flex gap-1.5 flex-wrap">
            {COLOR_PALETTE.map((color) => (
              <button
                key={color}
                onClick={() => updateMeta(s.id, "color", color)}
                className={`w-5 h-5 rounded-full border-2 transition-transform hover:scale-110 ${s.color === color ? "border-white scale-110 shadow-lg" : "border-transparent"}`}
                style={{ backgroundColor: color }}
                title={`Set color ${color}`}
              />
            ))}
          </div>
        </div>
      ))}
    </div>
  );
  
  // ==========================================
  // RENDER: VORDERSEITE (Leer)
  // ==========================================
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

  return (
    <GenericPluginWidget task={task} isConfigMode={isConfigMode} onUpdateTask={onUpdateTask} configContent={configContent}>
      <div
        className="h-full flex flex-col items-center justify-start p-2 pt-9 bg-slate-900 overflow-y-auto custom-scrollbar relative"
        onDragOver={handleDragOver}
        onDrop={handleDrop}
      >
        <div className="absolute top-2 right-2 flex items-center gap-2">
          <button
            onClick={togglePause}
            className={`p-1.5 rounded-full border transition-all ${isPaused
              ? "text-amber-200 bg-amber-900/40 border-amber-500/60"
              : "text-slate-300 bg-slate-900/70 border-slate-700/70 hover:bg-slate-800 hover:text-white"}`}
            title="Pause Anzeige"
          >
            {isPaused ? <Icons.Play size={14} /> : <Icons.Pause size={14} />}
          </button>
          <button
            onClick={toggleUncertainty}
            className={`p-1.5 rounded-full border transition-all ${showUncertainty
            ? "text-cyan-200 bg-cyan-900/40 border-cyan-500/60"
            : "text-slate-300 bg-slate-900/70 border-slate-700/70 hover:bg-slate-800 hover:text-white"}`}
            title="Fehlerbereich ein/aus"
          >
            <Icons.Sigma size={14} />
          </button>
        </div>
        {sources.map((s) => (
          <ChannelDisplay
            key={s.id}
            source={s}
            streamBuffers={streamBuffers}
            showUncertainty={showUncertainty}
            pausedSample={isPaused ? pausedSnapshot[s.id] : null}
          />
        ))}
      </div>
    </GenericPluginWidget>
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
          showUncertainty: false,
          isPaused: false,
        },
        ui: { mode: "generic", template: "tpl_metric" },
    }))
    .build();

