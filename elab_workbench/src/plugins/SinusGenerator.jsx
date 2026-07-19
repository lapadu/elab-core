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
            // Emit real-time-aligned chunks so 1 s of signal == 1 s of wall
            // clock. A continuous phase accumulator (NCO) keeps the waveform
            // clean across chunks and across live frequency changes.
            const EMIT_INTERVAL_MS = 50; // chunk cadence (wall clock)
            const SAMPLE_RATE = 2000; // Hz -> 20 samples/period at 100 Hz
            const SAMPLE_PERIOD_MS = 1000 / SAMPLE_RATE;
            const MAX_SAMPLES_PER_CHUNK = SAMPLE_RATE; // cap 1 s backlog

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

            let phase = 0; // radians, continuous oscillator phase
            let nextSampleTime = Date.now(); // wall-clock time of next sample
            const intervalId = setInterval(() => {
                const freq = Number(currentConfig.frequency) || 1;
                const amp = Number(currentConfig.amplitude) || 5;
                const noiseEnabled = currentConfig.noiseEnabled ?? true;
                const noiseLevel = currentConfig.noiseLevel || 0.1;

                // Emit exactly as many samples as fit into the elapsed wall
                // time, so the signal clock advances at 1x real time.
                const now = Date.now();
                let count = Math.floor((now - nextSampleTime) / SAMPLE_PERIOD_MS);
                if (count <= 0) return;
                if (count > MAX_SAMPLES_PER_CHUNK) {
                    // Drop stale backlog (e.g. throttled background tab) instead
                    // of emitting a large catch-up burst.
                    nextSampleTime = now - MAX_SAMPLES_PER_CHUNK * SAMPLE_PERIOD_MS;
                    count = MAX_SAMPLES_PER_CHUNK;
                }

                const startTime = nextSampleTime;
                const phaseInc = 2 * Math.PI * freq * (SAMPLE_PERIOD_MS / 1000);
                const values = [];
                for (let i = 0; i < count; i++) {
                    let val = amp * Math.sin(phase);
                    if (noiseEnabled) {
                        val += (Math.random() - 0.5) * amp * noiseLevel;
                    }
                    values.push(val);
                    phase += phaseInc;
                }
                // Keep the accumulator bounded without disturbing continuity.
                phase %= 2 * Math.PI;

                // endTime is the timestamp of the LAST sample (inclusive), to
                // match the canonical linear reconstruction dt = span/(count-1)
                // used by the workbench and actuator. Advancing nextSampleTime
                // by one extra period places the next chunk's first sample right
                // after this chunk's last one — no overlap, no boundary jump.
                const endTime = startTime + (count - 1) * SAMPLE_PERIOD_MS;
                nextSampleTime = startTime + count * SAMPLE_PERIOD_MS;

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
            }, EMIT_INTERVAL_MS);

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

