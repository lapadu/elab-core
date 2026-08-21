/* eslint-disable react-refresh/only-export-components */
import React from "react";
import dispatcher from "../services/DispatcherClient";
import { APP_EVENTS } from "../utils/EventTypes";
import { Icons } from "../utils/Shared";
import { useFactoryData } from "../hooks/useFactoryData";
import { useTask } from "../hooks/useTask";
import GenericPluginWidget from "../components/GenericPluginWidget";
import PluginBuilder from "./core/PluginBuilder";

const clampWindowSize = (value) => {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return 10;
  return Math.max(1, Math.min(1000, Math.round(parsed)));
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

const MeanWidget = ({ task, isConfigMode, onUpdateTask }) => {
  useFactoryData(task, MeanPlugin);

  const { updateConfig } = useTask(task, onUpdateTask);
  const source = task.inputs?.source || null;
  const meanWindow = clampWindowSize(task.config?.meanWindow ?? 10);

  const sendInputUpdate = (nextSource) => {
    const providerId = `prov_${task.originalId || task.id}`;
    dispatcher.sendControlCommand(providerId, {
      action: "update_input",
      payload: {
        source: toSourceRef(nextSource),
      },
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

      onUpdateTask({
        ...task,
        inputs: { source: nextSource },
        config: {
          ...task.config,
          unit: nextUnit,
        },
      });

      sendInputUpdate(nextSource);
    } catch (error) {
      console.error("Error handling source drop in Mean:", error);
    }
  };

  const handleDragOver = (e) => {
    e.preventDefault();
    e.stopPropagation();
  };

  const clearSource = () => {
    onUpdateTask({
      ...task,
      inputs: { source: null },
    });
    sendInputUpdate(null);
  };

  const configContent = (
    <div className="space-y-4">
      <div className="bg-slate-950 p-3 rounded-lg border border-slate-800">
        <label className="text-xs text-slate-400 block mb-2">Mittelwert Fenster (Anzahl Werte)</label>
        <input
          type="range"
          min="1"
          max="1000"
          step="1"
          value={meanWindow}
          onChange={(e) => updateConfig("meanWindow", clampWindowSize(e.target.value))}
          className="w-full accent-cyan-500"
        />
        <div className="text-[11px] text-slate-500 mt-1">{meanWindow} Werte</div>
      </div>

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
    </div>
  );

  if (isConfigMode) {
    return (
      <GenericPluginWidget task={task} isConfigMode={true} onUpdateTask={onUpdateTask} configContent={configContent} />
    );
  }

  return (
    <GenericPluginWidget task={task} isConfigMode={isConfigMode} onUpdateTask={onUpdateTask} configContent={configContent}>
      <div
        onDragOver={handleDragOver}
        onDrop={handleDrop}
        className="h-full p-4 bg-slate-900 overflow-y-auto custom-scrollbar"
      >
        {configContent}

        {!source && (
          <div className="mt-3 text-center text-slate-500 p-3 border-2 border-dashed border-slate-700 rounded bg-slate-950/30">
            <Icons.Inbox className="mx-auto mb-2 opacity-50" size={24} />
            <p className="text-[10px] text-slate-600">Genau ein Kanal als Eingang</p>
          </div>
        )}
      </div>
    </GenericPluginWidget>
  );
};

export const MeanPlugin = new PluginBuilder("system_mean_v1", "Moving Mean", "MATH")
  .setRender(MeanWidget)
  .setCapabilities(["process", "measure"])
  .setDescription("Bildet einen gleitenden Mittelwert auf einem Eingangskanal")
  .setSimulation({
    alwaysRun: true,
    factory: (initialTask, dispatcherClient) => {
      const providerId = `prov_${initialTask.originalId || initialTask.id}`;
      const outputSourceId = initialTask.originalId || initialTask.id;

      let currentConfig = { ...initialTask.config };
      let currentSource = toSourceRef(initialTask.inputs?.source);
      let currentOutputColor = initialTask.color;
      let windowValues = [];
      let runningSum = 0;

      const resetWindow = () => {
        windowValues = [];
        runningSum = 0;
      };

      const pushAndAverage = (sample, windowSize) => {
        const value = Number(sample);
        if (!Number.isFinite(value)) return null;

        windowValues.push(value);
        runningSum += value;

        while (windowValues.length > windowSize) {
          const removed = windowValues.shift();
          runningSum -= removed;
        }

        return {
          avg: runningSum / windowValues.length,
          n: windowValues.length,
        };
      };

      const propagateUncertainty = (inputUncertainty, sampleCount) => {
        if (!inputUncertainty || typeof inputUncertainty !== "object") return undefined;

        const n = Math.max(1, Number(sampleCount) || 1);
        const systematicAbs = Number(inputUncertainty.systematicAbs);
        const randomSigma = Number(inputUncertainty.randomSigma);

        const hasSystematic = Number.isFinite(systematicAbs);
        const hasRandom = Number.isFinite(randomSigma);
        if (!hasSystematic && !hasRandom) return undefined;

        return {
          ...inputUncertainty,
          domain: "decoded",
          model: "combined",
          systematicAbs: hasSystematic ? Math.abs(systematicAbs) : 0,
          randomSigma: hasRandom ? Math.abs(randomSigma) / Math.sqrt(n) : 0,
          propagatedBy: "system_mean",
          sampleCount: n,
        };
      };

      const currentSourceIds = () => {
        if (!currentSource) return [];
        return [currentSource.id, currentSource.originalId].filter(Boolean);
      };

      const emitAveragedPayload = (payload) => {
        if (!dispatcherClient.socket?.connected || !currentSource) return;

        const ids = currentSourceIds();
        if (!ids.includes(payload.sourceId)) return;

        const windowSize = clampWindowSize(currentConfig.meanWindow ?? 10);

        if (Array.isArray(payload.values) && payload.values.length > 0) {
          const outValues = [];
          let lastWindowN = 1;
          payload.values.forEach((raw) => {
            const result = pushAndAverage(raw, windowSize);
            if (result !== null) {
              outValues.push(result.avg);
              lastWindowN = result.n;
            }
          });
          if (outValues.length === 0) return;

          const outUncertainty = propagateUncertainty(payload.uncertainty, lastWindowN);

          dispatcherClient.socket.emit("data_stream", {
            sourceId: outputSourceId,
            values: outValues,
            value: outValues[outValues.length - 1],
            color: currentOutputColor,
            distribution: payload.distribution,
            startTime: payload.startTime,
            endTime: payload.endTime,
            timestamp: payload.timestamp ?? Date.now(),
            timestamps: Array.isArray(payload.timestamps) ? payload.timestamps : undefined,
            uncertainty: outUncertainty,
          });
          return;
        }

        if (payload.value !== undefined) {
          const result = pushAndAverage(payload.value, windowSize);
          if (result === null) return;

          const outUncertainty = propagateUncertainty(payload.uncertainty, result.n);

          dispatcherClient.socket.emit("data_stream", {
            sourceId: outputSourceId,
            value: result.avg,
            color: currentOutputColor,
            timestamp: payload.timestamp ?? Date.now(),
            uncertainty: outUncertainty,
          });
        }
      };

      const controlHandler = (data) => {
        if (data.provider_id !== providerId || !data.command) return;

        if (data.command.action === "update_config") {
          currentConfig = { ...currentConfig, ...data.command.payload };
          return;
        }

        if (data.command.action === "update_input") {
          const nextSource = toSourceRef(data.command.payload?.source);
          const prevId = currentSource?.originalId || currentSource?.id;
          const nextId = nextSource?.originalId || nextSource?.id;
          currentSource = nextSource;
          if (prevId !== nextId) {
            resetWindow();
          }
          return;
        }

        if (data.command.action === "update_meta") {
          if (data.command.payload?.color) {
            currentOutputColor = data.command.payload.color;
          }
        }
      };

      const dataHandler = (payload) => emitAveragedPayload(payload);

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
    id: `mean_${Date.now()}`,
    groupId: "system_mean_v1",
    type: "MATH",
    name: "Mean",
    color: "#06b6d4",
    virtual: true,
    inputs: { source: null },
    config: {
      meanWindow: 10,
      unit: "V",
      factor: 1.0,
    },
    ui: {
      mode: "generic",
      defaultTemplate: "system_mean",
      views: [
        {
          id: "config",
          label: "Konfig",
          icon: "Settings",
          template: "system_mean",
        },
      ],
    },
  }))
  .build();

// Separate template registration so the registry can resolve "system_mean"
export const MeanTemplate = {
  id: "system_mean",
  name: "Mean Config",
  type: "UI_TEMPLATE",
  render: MeanWidget,
};
