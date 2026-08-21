/* eslint-disable react-refresh/only-export-components */
import React, { useState, useEffect, useRef, useCallback, useMemo } from "react";
import { ColorPicker, Icons } from "../../../utils/Shared";
import dispatcher from "../../../services/DispatcherClient";
import { getConfig, getLatestValue } from "../utils/configUtils";

// ==========================================
// GENERIC METRIC TREND WIDGET (tpl_metric_trend)
// Shows latest scalar measurement in device color,
// background SVG trend chart (last 100 samples),
// Min & Max beneath value, and reset toolbar.
// ==========================================

const MAX_HISTORY = 100;

const MetricTrendWidget = ({
  task,
  isConfigMode,
  streamBuffers,
  onUpdateTask,
}) => {
  const [currentValue, setCurrentValue] = useState(null);
  const [history, setHistory] = useState([]);
  const [minVal, setMinVal] = useState(null);
  const [maxVal, setMaxVal] = useState(null);
  const requestRef = useRef(null);
  const resetTimestampRef = useRef(0);
  const historyRef = useRef([]);

  const primaryChannel = useMemo(() => {
    return task.inputs?.source || task;
  }, [task]);

  const config = getConfig(task, primaryChannel);
  const providerId = (task.providerId || task.config?.providerId || task.originalId || task.id || "").replace(/^prov_/, "");

  const handleReset = useCallback(() => {
    // Anchor to the stream's own clock so the marker works for any time base.
    const buffer = streamBuffers?.get(primaryChannel.originalId || primaryChannel.id);
    const data = buffer?.getData?.() || [];
    resetTimestampRef.current = data.length > 0 ? data[data.length - 1].t : 0;
    historyRef.current = [];
    setHistory([]);
    setMinVal(null);
    setMaxVal(null);
  }, [streamBuffers, primaryChannel]);

  const handleUnitToggle = useCallback(() => {
    const currentUnit = config.unit || task.config?.unit || "°C";
    let newUnit;
    if (currentUnit === "°C" || currentUnit === "C") {
      newUnit = "°F";
    } else if (currentUnit === "°F" || currentUnit === "F") {
      newUnit = "°C";
    } else {
      return;
    }

    // Update locally
    if (onUpdateTask) {
      onUpdateTask({
        ...task,
        config: { ...task.config, unit: newUnit },
      });
    }
    // Command backend provider to switch unit if applicable
    if (providerId) {
      dispatcher.sendControlCommand(`prov_${providerId}`, {
        action: "set_unit",
        payload: { task_id: task.originalId || task.id, unit: newUnit },
      });
    }
  }, [config.unit, task, onUpdateTask, providerId]);

  // Animation loop to gather stream history up to 100 items
  useEffect(() => {
    if (!streamBuffers) return;
    const channelId = primaryChannel.id;
    const originalId = primaryChannel.originalId;
    const buffer = streamBuffers.get(originalId || channelId);
    if (!buffer) return;

    let lastFpsTime = performance.now();

    const update = (now) => {
      if (now - lastFpsTime >= 50) {
        lastFpsTime = now;
        const data = buffer.getData ? buffer.getData() : [];
        if (data && data.length > 0) {
          // Filter points after reset timestamp
          const validData = resetTimestampRef.current > 0
            ? data.filter((p) => p.t >= resetTimestampRef.current)
            : data;

          if (validData.length > 0) {
            const recent = validData.slice(-MAX_HISTORY).map((p) => p.v);
            const latest = recent[recent.length - 1];

            if (
              recent.length !== historyRef.current.length ||
              latest !== currentValue ||
              recent[recent.length - 1] !== historyRef.current[historyRef.current.length - 1]
            ) {
              historyRef.current = recent;
              setHistory(recent);
              setCurrentValue(latest);
              setMinVal(Math.min(...recent));
              setMaxVal(Math.max(...recent));
            }
          } else if (currentValue !== null && resetTimestampRef.current > 0) {
            setCurrentValue(null);
            setHistory([]);
            setMinVal(null);
            setMaxVal(null);
          }
        } else {
          // Fallback if scalar only
          const fallbackVal = getLatestValue(streamBuffers, channelId, originalId);
          if (fallbackVal !== null && fallbackVal !== currentValue && fallbackVal !== undefined) {
            const updated = [...historyRef.current, fallbackVal].slice(-MAX_HISTORY);
            historyRef.current = updated;
            setHistory(updated);
            setCurrentValue(fallbackVal);
            setMinVal(Math.min(...updated));
            setMaxVal(Math.max(...updated));
          }
        }
      }
      requestRef.current = requestAnimationFrame(update);
    };

    requestRef.current = requestAnimationFrame(update);
    return () => {
      if (requestRef.current) cancelAnimationFrame(requestRef.current);
    };
  }, [streamBuffers, primaryChannel, currentValue]);

  // Formatting display values
  const displayColor = primaryChannel.color || task.color || "#3b82f6";
  const factor = config.factor ?? 1.0;
  const displayVal = currentValue !== null && currentValue !== undefined ? (currentValue * factor).toFixed(1) : "---";
  const displayMin = minVal !== null && minVal !== undefined ? (minVal * factor).toFixed(1) : "--";
  const displayMax = maxVal !== null && maxVal !== undefined ? (maxVal * factor).toFixed(1) : "--";
  const unitStr = config.unit || "";
  const showUnitToggle = unitStr === "°C" || unitStr === "°F" || unitStr === "C" || unitStr === "F";

  // Build smooth SVG Chart representation for the last 100 measurements
  const chartPoints = useMemo(() => {
    if (!history || history.length < 2) return null;
    const width = 800;
    const height = 240;
    const padding = 15;
    const min = minVal !== null ? minVal * factor : 0;
    const max = maxVal !== null ? maxVal * factor : 1;
    const span = max - min === 0 ? Math.abs(max) * 0.2 || 1 : max - min;

    const step = width / Math.max(MAX_HISTORY - 1, history.length - 1);
    const startX = width - (history.length - 1) * step;

    const coords = history.map((val, i) => {
      const x = startX + i * step;
      const normalized = (val * factor - min) / span;
      const y = height - padding - normalized * (height - 2 * padding);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    });

    const lineString = coords.join(" ");
    const firstX = startX.toFixed(1);
    const lastX = (startX + (history.length - 1) * step).toFixed(1);
    const areaString = `${firstX},${height} ${lineString} ${lastX},${height}`;

    return { lineString, areaString };
  }, [history, minVal, maxVal, factor]);

  // Config Mode View
  if (isConfigMode) {
    return (
      <div className="p-4 space-y-4 bg-slate-900 h-full overflow-y-auto custom-scrollbar">
        <ColorPicker task={task} onUpdateTask={onUpdateTask} />
        <div className="border-t border-slate-800 pt-3">
          <label className="text-xs text-slate-400 uppercase tracking-wider block mb-2 font-bold">
            Unit & Control
          </label>
          <div className="flex gap-2 items-center">
            <button
              onClick={handleUnitToggle}
              className="px-3 py-1.5 rounded-lg text-xs font-mono font-bold bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 transition-colors flex items-center gap-1.5"
              title="Toggle Unit (°C/°F)"
            >
              <Icons.Repeat size={14} /> Switch Unit ({config.unit || "N/A"})
            </button>
            <button
              onClick={handleReset}
              className="px-3 py-1.5 rounded-lg text-xs font-mono font-bold bg-slate-800 hover:bg-red-900/40 text-slate-300 hover:text-red-300 border border-slate-700 transition-colors flex items-center gap-1.5"
            >
              <Icons.RotateCcw size={14} /> Reset Min/Max
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="h-full w-full relative flex flex-col items-center justify-center p-4 bg-gradient-to-b from-slate-900 to-slate-950 overflow-hidden select-none">
      {/* Top Toolbar */}
      <div className="absolute top-2 left-3 right-3 flex justify-between items-center z-20">
        <div className="flex items-center gap-2 max-w-[65%] truncate">
          <span
            className="w-2.5 h-2.5 rounded-full inline-block shrink-0 shadow-sm"
            style={{ backgroundColor: displayColor, boxShadow: `0 0 8px ${displayColor}` }}
          />
          <span className="text-[11px] font-bold tracking-wider text-slate-400 uppercase truncate">
            {primaryChannel.name || task.name}
          </span>
          {primaryChannel.config?.simulated && (
            <span className="px-1.5 py-0.5 rounded text-[8px] font-mono font-extrabold tracking-wider bg-amber-950/60 text-amber-500 border border-amber-800/60 uppercase shrink-0">
              Simulated
            </span>
          )}
        </div>
        <div className="flex items-center gap-1.5 z-20 pointer-events-auto">
          {showUnitToggle && (
            <button
              onClick={handleUnitToggle}
              className="px-2 py-0.5 text-[10px] font-mono font-extrabold rounded-md bg-slate-800/80 hover:bg-slate-700 text-slate-300 hover:text-white border border-slate-700/60 shadow-sm transition-all backdrop-blur-sm"
              title="Switch between °C and °F"
            >
              {unitStr}
            </button>
          )}
          <button
            onClick={handleReset}
            className="p-1.5 rounded-md bg-slate-800/80 hover:bg-slate-700 text-slate-400 hover:text-white border border-slate-700/60 shadow-sm transition-all backdrop-blur-sm active:scale-95"
            title="Reset Chart History and Min/Max"
          >
            <Icons.RotateCcw size={13} />
          </button>
        </div>
      </div>

      {/* Background SVG Trend Chart (Last 100 points) */}
      <div className="absolute inset-0 z-0 opacity-80 pointer-events-none">
        {chartPoints ? (
          <svg className="w-full h-full preserve-3d" viewBox="0 0 800 240" preserveAspectRatio="none">
            <defs>
              <linearGradient id={`grad-${task.id}`} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={displayColor} stopOpacity="0.45" />
                <stop offset="80%" stopColor={displayColor} stopOpacity="0.03" />
                <stop offset="100%" stopColor={displayColor} stopOpacity="0.0" />
              </linearGradient>
            </defs>
            <polygon points={chartPoints.areaString} fill={`url(#grad-${task.id})`} />
            <polyline
              points={chartPoints.lineString}
              fill="none"
              stroke={displayColor}
              strokeWidth="3.5"
              strokeLinecap="round"
              strokeLinejoin="round"
              style={{ filter: `drop-shadow(0 0 6px ${displayColor}80)` }}
            />
          </svg>
        ) : (
          <div className="w-full h-full flex items-center justify-center text-[11px] font-mono text-slate-700 uppercase tracking-widest">
            Gathering trend data...
          </div>
        )}
      </div>

      {/* Foreground Main Display Value */}
      <div className="relative z-10 flex flex-col items-center justify-center my-auto pt-4 pointer-events-none">
        <div
          className="text-6xl sm:text-7xl font-mono font-extrabold tracking-tight drop-shadow-[0_4px_16px_rgba(0,0,0,0.8)] transition-colors duration-300"
          style={{ color: displayColor }}
        >
          {displayVal}
          <span className="text-3xl sm:text-4xl font-sans text-slate-400 ml-1.5 font-bold">
            {unitStr}
          </span>
        </div>

        {/* Beneath value: small Min and Max values */}
        <div className="flex items-center gap-4 mt-3 px-3 py-1 rounded-full bg-slate-950/70 border border-slate-800/80 shadow-lg backdrop-blur-md text-[11px] font-mono text-slate-300 tracking-wider">
          <div className="flex items-center gap-1.5">
            <span className="text-[10px] text-slate-500 font-bold uppercase">Min</span>
            <span className="font-extrabold text-slate-200">{displayMin}</span>
          </div>
          <span className="text-slate-700">|</span>
          <div className="flex items-center gap-1.5">
            <span className="text-[10px] text-slate-500 font-bold uppercase">Max</span>
            <span className="font-extrabold text-slate-200">{displayMax}</span>
          </div>
        </div>
      </div>
    </div>
  );
};

export const MetricTrendPlugin = {
  id: "tpl_metric_trend",
  name: "Metric Trend Display",
  type: "UI_TEMPLATE",
  render: MetricTrendWidget,
};
