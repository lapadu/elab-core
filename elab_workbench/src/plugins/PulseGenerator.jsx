import React from "react";
import { Icons, ColorPicker } from "../utils/Shared";
import { useFactoryData } from "../hooks/useFactoryData";
import { useTask } from "../hooks/useTask";

import GenericPluginWidget from "../components/GenericPluginWidget";

import SliderControl from "../components/SliderControl";

const PulseGenWidget = ({ task, isConfigMode, onUpdateTask }) => {
  // Use the shared adapter hook with the simulation plugin defined below.
  useFactoryData(task, SquareWavePlugin);

  const { updateConfig } = useTask(task, onUpdateTask);

  const frequency = task.config?.frequency || 2;
  const amplitude = task.config?.amplitude || 5;

  return (
    <GenericPluginWidget task={task} isConfigMode={isConfigMode} onUpdateTask={onUpdateTask}>
      <div className="p-4 flex-1 flex flex-col">
        <div className="flex items-center gap-2 mb-6 border-b border-slate-800 pb-2">
          <Icons.Zap className="text-blue-500" size={20} />
          <span className="font-bold text-sm tracking-widest uppercase">
            Pulse Gen
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
            colorClass="accent-blue-500"
            textColorClass="text-blue-400"
          />
          <SliderControl
            label="Amplitude"
            value={amplitude}
            min="0.1"
            max="10"
            step="0.1"
            onChange={(e) => updateConfig("amplitude", Number(e.target.value))}
            unit="V"
            colorClass="accent-blue-500"
            textColorClass="text-blue-400"
          />
        </div>
      </div>
    </GenericPluginWidget>
  );
};

import PluginBuilder from "./core/PluginBuilder";

export const PulseGenTemplate = new PluginBuilder("system_pulse_gen", "Pulse Generator UI", "UI_TEMPLATE")
    .setRender(PulseGenWidget)
    .build();

// Simulation definition
export const SquareWavePlugin = new PluginBuilder("system_square_v1", "Virtual Pulse Gen", "SENSOR")
    .setCapabilities(["generate", "measure"])
    .setDescription("Generates a square wave")
    .setSimulation({
        alwaysRun: true,
        factory: (initialTask, dispatcher) => {
          // Emit real-time-aligned chunks so 1 s of signal == 1 s of wall
          // clock. A continuous phase accumulator keeps the duty cycle clean
          // across chunks and across live frequency changes.
          const EMIT_INTERVAL_MS = 50; // chunk cadence (wall clock)
          const SAMPLE_RATE = 2000; // Hz -> 20 samples/period at 100 Hz
          const SAMPLE_PERIOD_MS = 1000 / SAMPLE_RATE;
          const MAX_SAMPLES_PER_CHUNK = SAMPLE_RATE; // cap 1 s backlog

          // Keep mutable runtime config inside the closure.
          let currentConfig = { ...initialTask.config };

          // Listen for control commands directly on the dispatcher socket so
          // runtime config changes can update the simulation.
          const providerId = `prov_${initialTask.originalId || initialTask.id}`;

          const controlHandler = (data) => {
            if (
              data.provider_id === providerId &&
              data.command?.action === "update_config"
            ) {
              currentConfig = { ...currentConfig, ...data.command.payload };
            }
          };

          // Attach directly to the socket for this simulation path.
          if (dispatcher.socket) {
            dispatcher.socket.on("execute_command", controlHandler);
          }

          let phase = 0; // normalized [0, 1) position within the period
          let nextSampleTime = Date.now(); // wall-clock time of next sample
          const intervalId = setInterval(() => {
            const freq = Number(currentConfig.frequency) || 2;
            const amp = Number(currentConfig.amplitude) || 5;

            // Emit exactly as many samples as fit into the elapsed wall time,
            // so the signal clock advances at 1x real time.
            const now = Date.now();
            let count = Math.floor((now - nextSampleTime) / SAMPLE_PERIOD_MS);
            if (count <= 0) return;
            if (count > MAX_SAMPLES_PER_CHUNK) {
              // Drop stale backlog (e.g. throttled background tab) instead of
              // emitting a large catch-up burst.
              nextSampleTime = now - MAX_SAMPLES_PER_CHUNK * SAMPLE_PERIOD_MS;
              count = MAX_SAMPLES_PER_CHUNK;
            }

            const startTime = nextSampleTime;
            const phaseInc = freq * (SAMPLE_PERIOD_MS / 1000);
            const values = [];
            for (let i = 0; i < count; i++) {
              // 50% duty cycle: high for the first half of the period.
              values.push(phase < 0.5 ? amp : 0);
              phase += phaseInc;
              if (phase >= 1) phase -= Math.floor(phase);
            }

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
            }
          };
        },
    })
    .setCreateTask(() => ({
        id: `pulse_${Date.now()}`,
        groupId: "system_square_v1",
        type: "GENERATOR",
        name: "Pulse Gen",
        color: "#3b82f6",
        virtual: true,
        config: {
          frequency: 2,
          amplitude: 5,
          range: [0, 5],
          unit: "V",
          factor: 1.0,
        },
        ui: {
          mode: "generic",
          defaultTemplate: "system_pulse_gen",
          views: [
            {
              id: "control",
              label: "Control",
              icon: "Settings",
              template: "system_pulse_gen",
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

