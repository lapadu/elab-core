/* eslint-disable react-refresh/only-export-components */
import React from "react";
import dispatcher from "../services/DispatcherClient";
import { APP_EVENTS } from "../utils/EventTypes";
import { Icons } from "../utils/Shared";
import { useFactoryData } from "../hooks/useFactoryData";
import { useTask } from "../hooks/useTask";
import GenericPluginWidget from "../components/GenericPluginWidget";
import PluginBuilder from "./core/PluginBuilder";

const clampOrder = (value) => {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return 51;
  // FIR order must be odd for symmetric filters
  const clamped = Math.max(3, Math.min(255, Math.round(parsed)));
  return clamped % 2 === 0 ? clamped + 1 : clamped;
};

const clampCutoff = (value, sampleRate) => {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return 100;
  return Math.max(1, Math.min(sampleRate / 2 - 1, Math.round(parsed)));
};

const toSourceRef = (taskRef) => {
  if (!taskRef) return null;
  return {
    id: taskRef.id,
    originalId: taskRef.originalId || taskRef.id,
    name: taskRef.name,
    color: taskRef.color,
    config: taskRef.config || {},
    providerId: taskRef.providerId,
  };
};

/**
 * Generate FIR lowpass coefficients using a windowed-sinc method.
 * Pure JS implementation – no scipy dependency needed in the browser.
 */
const designFirLowpass = (order, cutoffHz, sampleRate, windowType = "hamming") => {
  const fc = cutoffHz / sampleRate; // normalized cutoff (0..0.5)
  const N = order;
  const M = (N - 1) / 2;
  const coeffs = new Float64Array(N);

  // Windowed sinc
  for (let n = 0; n < N; n++) {
    const x = n - M;
    // sinc
    if (Math.abs(x) < 1e-12) {
      coeffs[n] = 2 * fc;
    } else {
      coeffs[n] = Math.sin(2 * Math.PI * fc * x) / (Math.PI * x);
    }
    // window
    coeffs[n] *= windowFunction(n, N, windowType);
  }

  // Normalize to unity gain at DC
  let sum = 0;
  for (let i = 0; i < N; i++) sum += coeffs[i];
  if (sum !== 0) {
    for (let i = 0; i < N; i++) coeffs[i] /= sum;
  }

  return coeffs;
};

const windowFunction = (n, N, type) => {
  switch (type) {
    case "hann":
      return 0.5 * (1 - Math.cos((2 * Math.PI * n) / (N - 1)));
    case "blackman":
      return (
        0.42 -
        0.5 * Math.cos((2 * Math.PI * n) / (N - 1)) +
        0.08 * Math.cos((4 * Math.PI * n) / (N - 1))
      );
    case "boxcar":
      return 1.0;
    case "hamming":
    default:
      return 0.54 - 0.46 * Math.cos((2 * Math.PI * n) / (N - 1));
  }
};

const WINDOW_OPTIONS = [
  { value: "hamming", label: "Hamming" },
  { value: "hann", label: "Hann" },
  { value: "blackman", label: "Blackman" },
  { value: "boxcar", label: "Rectangular" },
];

const FirFilterWidget = ({ task, isConfigMode, onUpdateTask }) => {
  useFactoryData(task, FirFilterPlugin);

  const { updateConfig } = useTask(task, onUpdateTask);
  const source = task.inputs?.source || null;
  const sampleRate = task.config?.sampleRate || 10000;
  const cutoff = clampCutoff(task.config?.cutoffFreq ?? 100, sampleRate);
  const order = clampOrder(task.config?.filterOrder ?? 51);
  const windowType = task.config?.windowType || "hamming";
  const enabled = task.config?.enabled !== false;

  const sendInputUpdate = (nextSource) => {
    const providerId = `prov_${task.originalId || task.id}`;
    dispatcher.sendControlCommand(providerId, {
      action: "update_input",
      payload: { source: toSourceRef(nextSource) },
    });
  };

  const handleDrop = (e) => {
    e.preventDefault();
    e.stopPropagation();
    try {
      const droppedTask = JSON.parse(e.dataTransfer.getData("task"));
      if (!droppedTask || droppedTask.id === task.id) return;

      const nextSource = toSourceRef(droppedTask);
      const nextUnit = nextSource?.config?.unit || task.config?.unit || "";
      const nextSampleRate = nextSource?.config?.sampleRate || sampleRate;

      onUpdateTask({
        ...task,
        inputs: { source: nextSource },
        config: {
          ...task.config,
          unit: nextUnit,
          sampleRate: nextSampleRate,
        },
      });
      sendInputUpdate(nextSource);
    } catch (error) {
      console.error("Error handling source drop in FIR Filter:", error);
    }
  };

  const handleDragOver = (e) => {
    e.preventDefault();
    e.stopPropagation();
  };

  const clearSource = () => {
    onUpdateTask({ ...task, inputs: { source: null } });
    sendInputUpdate(null);
  };

  const configContent = (
    <div className="space-y-3">
      {/* Enable toggle */}
      <div className="bg-slate-950 p-3 rounded-lg border border-slate-800 flex items-center justify-between">
        <span className="text-xs text-slate-300">Filter aktiv</span>
        <button
          onClick={() => updateConfig("enabled", !enabled)}
          className={`w-9 h-5 rounded-full transition-colors relative ${enabled ? "bg-cyan-600" : "bg-slate-700"}`}
        >
          <span
            className={`absolute top-0.5 w-4 h-4 rounded-full bg-white transition-transform ${enabled ? "left-[18px]" : "left-0.5"}`}
          />
        </button>
      </div>

      {/* Cutoff Frequency */}
      <div className="bg-slate-950 p-3 rounded-lg border border-slate-800">
        <label className="text-xs text-slate-400 block mb-2">Cutoff-Frequenz</label>
        <input
          type="range"
          min="1"
          max={Math.floor(sampleRate / 2 - 1)}
          step="1"
          value={cutoff}
          onChange={(e) => updateConfig("cutoffFreq", clampCutoff(e.target.value, sampleRate))}
          className="w-full accent-cyan-500"
        />
        <div className="text-[11px] text-slate-500 mt-1">{cutoff} Hz</div>
      </div>

      {/* Filter Order */}
      <div className="bg-slate-950 p-3 rounded-lg border border-slate-800">
        <label className="text-xs text-slate-400 block mb-2">Filter-Ordnung (Taps)</label>
        <input
          type="range"
          min="3"
          max="255"
          step="2"
          value={order}
          onChange={(e) => updateConfig("filterOrder", clampOrder(e.target.value))}
          className="w-full accent-cyan-500"
        />
        <div className="text-[11px] text-slate-500 mt-1">{order} Taps</div>
      </div>

      {/* Window Function */}
      <div className="bg-slate-950 p-3 rounded-lg border border-slate-800">
        <label className="text-xs text-slate-400 block mb-2">Fensterfunktion</label>
        <select
          value={windowType}
          onChange={(e) => updateConfig("windowType", e.target.value)}
          className="w-full bg-slate-900 text-xs text-slate-200 border border-slate-700 rounded px-2 py-1.5 focus:outline-none focus:border-cyan-600"
        >
          {WINDOW_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>
      </div>

      {!isConfigMode && (
        <div
          onDragOver={handleDragOver}
          onDrop={handleDrop}
          className="bg-slate-950 p-3 rounded-lg border border-slate-800"
        >
          <div className="text-xs text-slate-400 mb-2">Eingangskanal (max. 1)</div>
          {source ? (
            <div className="flex items-center justify-between gap-2">
              <div className="flex items-center gap-2 min-w-0">
                <span
                  className="w-2.5 h-2.5 rounded-full shrink-0"
                  style={{ backgroundColor: source.color || "#64748b" }}
                />
                <span className="text-xs text-slate-200 truncate">{source.name || source.id}</span>
              </div>
              <button
                onClick={clearSource}
                className="text-slate-500 hover:text-red-400 hover:bg-red-900/20 p-1 rounded transition-colors"
                title="Eingang entfernen"
              >
                <Icons.Trash2 size={14} />
              </button>
            </div>
          ) : (
            <div className="text-[11px] text-slate-500 italic">
              Sensor oder Generator hier hineinziehen
            </div>
          )}
        </div>
      )}
    </div>
  );

  if (isConfigMode) {
    return (
      <GenericPluginWidget task={task} isConfigMode={true} onUpdateTask={onUpdateTask} configContent={configContent} />
    );
  }

  return (
    <GenericPluginWidget task={task} isConfigMode={isConfigMode} onUpdateTask={onUpdateTask} configContent={configContent}>
      <div onDragOver={handleDragOver} onDrop={handleDrop} className="h-full p-4 bg-slate-900 overflow-y-auto custom-scrollbar">
        {configContent}

        {!source && (
          <div className="mt-3 text-center text-slate-500 p-3 border-2 border-dashed border-slate-700 rounded bg-slate-950/30">
            <Icons.Inbox className="mx-auto mb-2 opacity-50" size={24} />
            <p className="text-[10px] text-slate-600">Sensor oder Generator als Eingang zuweisen</p>
          </div>
        )}
      </div>
    </GenericPluginWidget>
  );
};

export const FirFilterPlugin = new PluginBuilder("system_fir_filter_v1", "FIR Filter", "MATH")
  .setRender(FirFilterWidget)
  .setCapabilities(["process", "measure"])
  .setDescription("Konfigurierbarer FIR-Tiefpassfilter (Windowed Sinc)")
  .setSimulation({
    alwaysRun: true,
    factory: (initialTask, dispatcherClient) => {
      const providerId = `prov_${initialTask.originalId || initialTask.id}`;
      const outputSourceId = initialTask.originalId || initialTask.id;

      let currentConfig = { ...initialTask.config };
      let currentSource = toSourceRef(initialTask.inputs?.source);
      let currentOutputColor = initialTask.color;

      // FIR filter state
      let coeffs = designFirLowpass(
        clampOrder(currentConfig.filterOrder ?? 51),
        clampCutoff(currentConfig.cutoffFreq ?? 100, currentConfig.sampleRate || 10000),
        currentConfig.sampleRate || 10000,
        currentConfig.windowType || "hamming",
      );
      let delayLine = new Float64Array(coeffs.length).fill(0);

      const rebuildFilter = () => {
        const sr = currentConfig.sampleRate || 10000;
        coeffs = designFirLowpass(
          clampOrder(currentConfig.filterOrder ?? 51),
          clampCutoff(currentConfig.cutoffFreq ?? 100, sr),
          sr,
          currentConfig.windowType || "hamming",
        );
        delayLine = new Float64Array(coeffs.length).fill(0);
      };

      /** Apply FIR filter sample-by-sample using a delay line. */
      const filterSample = (sample) => {
        const N = coeffs.length;
        // Shift delay line
        for (let i = N - 1; i > 0; i--) {
          delayLine[i] = delayLine[i - 1];
        }
        delayLine[0] = sample;

        // Convolve
        let out = 0;
        for (let i = 0; i < N; i++) {
          out += coeffs[i] * delayLine[i];
        }
        return out;
      };

      const currentSourceIds = () => {
        if (!currentSource) return [];
        return [currentSource.id, currentSource.originalId].filter(Boolean);
      };

      const processPayload = (payload) => {
        if (!dispatcherClient.socket?.connected || !currentSource) return;
        if (currentConfig.enabled === false) return;

        const ids = currentSourceIds();
        if (!ids.includes(payload.sourceId)) return;

        if (Array.isArray(payload.values) && payload.values.length > 0) {
          const outValues = [];
          payload.values.forEach((raw) => {
            const v = Number(raw);
            if (Number.isFinite(v)) outValues.push(filterSample(v));
          });
          if (outValues.length === 0) return;

          dispatcherClient.socket.emit("data_stream", {
            sourceId: outputSourceId,
            values: outValues,
            value: outValues[outValues.length - 1],
            color: currentOutputColor,
            distribution: payload.distribution,
            startTime: payload.startTime,
            endTime: payload.endTime,
            timestamp: payload.timestamp || Date.now(),
            timestamps: Array.isArray(payload.timestamps) ? payload.timestamps : undefined,
          });
          return;
        }

        if (payload.value !== undefined) {
          const v = Number(payload.value);
          if (!Number.isFinite(v)) return;
          const filtered = filterSample(v);

          dispatcherClient.socket.emit("data_stream", {
            sourceId: outputSourceId,
            value: filtered,
            color: currentOutputColor,
            timestamp: payload.timestamp || Date.now(),
          });
        }
      };

      const controlHandler = (data) => {
        if (data.provider_id !== providerId || !data.command) return;

        if (data.command.action === "update_config") {
          currentConfig = { ...currentConfig, ...data.command.payload };
          rebuildFilter();
          return;
        }

        if (data.command.action === "update_input") {
          const nextSource = toSourceRef(data.command.payload?.source);
          const prevId = currentSource?.originalId || currentSource?.id;
          const nextId = nextSource?.originalId || nextSource?.id;
          currentSource = nextSource;
          if (prevId !== nextId) {
            delayLine.fill(0);
          }
          return;
        }

        if (data.command.action === "update_meta") {
          if (data.command.payload?.color) {
            currentOutputColor = data.command.payload.color;
          }
        }
      };

      const dataHandler = (payload) => processPayload(payload);

      if (dispatcherClient.socket) {
        dispatcherClient.socket.on("execute_command", controlHandler);
      }
      dispatcherClient.on(APP_EVENTS.ON_DATA_STREAM, dataHandler);

      return () => {
        if (dispatcherClient.socket) {
          dispatcherClient.socket.off("execute_command", controlHandler);
        }
        dispatcherClient.off(APP_EVENTS.ON_DATA_STREAM, dataHandler);
      };
    },
  })
  .setCreateTask(() => ({
    id: `fir_${Date.now()}`,
    groupId: "system_fir_filter_v1",
    type: "MATH",
    name: "FIR Filter",
    color: "#3b82f6",
    virtual: true,
    inputs: { source: null },
    config: {
      cutoffFreq: 100,
      filterOrder: 51,
      windowType: "hamming",
      sampleRate: 10000,
      enabled: true,
      unit: "V",
      factor: 1.0,
    },
    ui: {
      mode: "generic",
      defaultTemplate: "system_fir_filter",
      views: [
        {
          id: "config",
          label: "Konfig",
          icon: "Settings",
          template: "system_fir_filter",
        },
      ],
    },
  }))
  .build();

// Separate template registration so the registry can resolve "system_fir_filter"
export const FirFilterTemplate = {
  id: "system_fir_filter",
  name: "FIR Filter Config",
  type: "UI_TEMPLATE",
  render: FirFilterWidget,
};
