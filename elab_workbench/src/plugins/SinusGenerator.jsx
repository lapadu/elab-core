import React from "react";
import { Icons, ColorPicker } from "../utils/Shared";
import { useFactoryData } from "../hooks/useFactoryData";
import { useTask } from "../hooks/useTask";

import GenericPluginWidget from "../components/GenericPluginWidget";

import SliderControl from "../components/SliderControl";

const SinusGenWidget = ({ task, isConfigMode, onUpdateTask }) => {
  useFactoryData(task, SineGenClientPlugin);

  const { updateConfig } = useTask(task, onUpdateTask);

  const frequency = task.config?.frequency || 1;
  const amplitude = task.config?.amplitude || 5;
  const noiseEnabled = task.config?.noiseEnabled ?? true;

  return (
    <GenericPluginWidget task={task} isConfigMode={isConfigMode} onUpdateTask={onUpdateTask}>
      <div className="p-4 flex-1 flex flex-col">
        <div className="flex items-center gap-2 mb-6 border-b border-slate-800 pb-2">
          <Icons.Zap className="text-green-500" size={20} />
          <span className="font-bold text-sm tracking-widest uppercase">
            Sine Gen
          </span>
        </div>

        <div className="space-y-6">
          <SliderControl
            label="Frequency"
            value={frequency}
            min="0.1"
            max="100"
            step="0.1"
            onChange={(e) => updateConfig("frequency", Number(e.target.value))}
            unit="Hz"
            colorClass="accent-green-500"
            textColorClass="text-green-400"
          />
          <SliderControl
            label="Amplitude"
            value={amplitude}
            min="0.1"
            max="10"
            step="0.1"
            onChange={(e) => updateConfig("amplitude", Number(e.target.value))}
            unit="V"
            colorClass="accent-green-500"
            textColorClass="text-green-400"
          />
          
          {/* Noise Toggle */}
          <div className="flex items-center gap-2 pt-2">
              <input 
                type="checkbox" 
                id={`noise-toggle-${task.id}`}
                checked={noiseEnabled}
                
                onChange={(e) => updateConfig("noiseEnabled", e.target.checked)}
                className="form-checkbox h-4 w-4 bg-slate-800 border-slate-700 text-green-500 rounded focus:ring-green-500"
              />
              <label htmlFor={`noise-toggle-${task.id}`} className="text-xs text-slate-400 font-bold uppercase">Enable Noise</label>
          </div>
        </div>
      </div>
    </GenericPluginWidget>
  );
};

import PluginBuilder from "./core/PluginBuilder";

export const SinusGenTemplate = new PluginBuilder("system_sine_gen", "Sine Generator UI", "UI_TEMPLATE")
    .setRender(SinusGenWidget)
    .build();

// Plugin to control a client-side sine generator
export const SineGenClientPlugin = new PluginBuilder("plugin_sine_gen_v1", "Client Sine Gen", "SENSOR")
    .setCapabilities(["generate", "measure"])
    .setDescription("Generiert ein Sinussignal")
    .setSimulation({
        alwaysRun: true,
        factory: (initialTask, dispatcher) => {
            const CHUNK_SIZE = 1024;
            const SAMPLE_RATE = 2000;

            let currentConfig = { ...initialTask.config };

            const providerId = `prov_${initialTask.originalId || initialTask.id}`;

            const controlHandler = (data) => {
                if (
                    data.provider_id === providerId &&
                    data.command?.action === "update_config"
                ) {
                    currentConfig = { ...currentConfig, ...data.command.payload };
                }
            };

            // Reagiere auf externe Config-Aenderungen (z.B. von Hardware-Clients)
            const metaChangedHandler = (data) => {
                const taskId = initialTask.originalId || initialTask.id;
                if (data.task_id === taskId && data.changes?.config) {
                    currentConfig = { ...currentConfig, ...data.changes.config };
                }
            };
            
            if (dispatcher.socket) {
                dispatcher.socket.on("execute_command", controlHandler);
                dispatcher.socket.on("provider_meta_changed", metaChangedHandler);
            }

            let lastEndTime = 0;
            const intervalId = setInterval(() => {
                const freq = Number(currentConfig.frequency) || 1;
                const amp = Number(currentConfig.amplitude) || 5;
                const noiseEnabled = currentConfig.noiseEnabled ?? true;
                const noiseLevel = currentConfig.noiseLevel || 0.1;

                const now = Date.now();
                const durationMs = (CHUNK_SIZE / SAMPLE_RATE) * 1000;
                let startTime = now - durationMs;
                let endTime = now;

                // Prevent backwards time jumps by moving overlapping chunks forward.
                if (lastEndTime && startTime <= lastEndTime) {
                    startTime = lastEndTime + 1;
                    endTime = startTime + durationMs;
                }

                const values = [];
                for (let i = 0; i < CHUNK_SIZE; i++) {
                    const tMs = startTime + (i / SAMPLE_RATE) * 1000;
                    const tSec = tMs / 1000;
                    // Generate the sine signal.
                    let val = amp * Math.sin(2 * Math.PI * freq * tSec);
                    if (noiseEnabled) {
                        val += (Math.random() - 0.5) * amp * noiseLevel;
                    }
                    values.push(val);
                }

                lastEndTime = endTime;

                const payload = {
                    // Use the original task ID (if present) so that viewers and other
                    // consumers always see the same stream key even if the UI task is
                    // replicated / cloned.
                    sourceId: initialTask.originalId || initialTask.id,
                    values: values,
                    value: values[values.length - 1],
                    distribution: "linear",
                    startTime: startTime,
                    endTime: endTime,
                    timestamp: endTime,
                };

                if (dispatcher.socket?.connected) {
                    dispatcher.socket.emit("data_stream", payload);
                }
            }, 50);

            return () => {
                clearInterval(intervalId);
                if (dispatcher.socket) {
                    dispatcher.socket.off("execute_command", controlHandler);
                    dispatcher.socket.off("provider_meta_changed", metaChangedHandler);
                }
            };
        },
    })
    .setCreateTask(() => ({
        id: `sine_${Date.now()}`,
        groupId: "system_sine_v1",
        type: "GENERATOR",
        name: "Sine Gen",
        color: "#22c55e", // green-500
        virtual: true,
        tags: ["Sine", "JS"],
        config: {
            frequency: 1,
            amplitude: 5,
            range: [-5, 5],
            unit: "V",
            factor: 1.0,
        },
        ui: {
            mode: "generic",
            defaultTemplate: "system_sine_gen",
            views: [
                {
                    id: "control",
                    label: "Control",
                    icon: "Settings",
                    template: "system_sine_gen",
                },
                {
                    id: "metric",
                    label: "Metric",
                    icon: "Maximize2",
                    template: "tpl_metric",
                },
            ],
        },
    }))
    .build();

