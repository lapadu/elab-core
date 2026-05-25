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
          const CHUNK_SIZE = 50;
          const SAMPLE_RATE = 1000;
    
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
    
          const intervalId = setInterval(() => {
            const freq = Number(currentConfig.frequency) || 2;
            const amp = Number(currentConfig.amplitude) || 5;
            const now = Date.now();
            const startTime = now - (CHUNK_SIZE / SAMPLE_RATE) * 1000;
    
            const values = [];
            for (let i = 0; i < CHUNK_SIZE; i++) {
              const tMs = startTime + (i / SAMPLE_RATE) * 1000;
              const tSec = tMs / 1000;
              // Generate the square wave.
              const signal = Math.sin(2 * Math.PI * freq * tSec);
              const val = signal >= 0 ? amp : 0;
              values.push(val);
            }
    
            const payload = {
              // Use the original task ID (if present) so that viewers and other
              // consumers always see the same stream key even if the UI task is
              // replicated / cloned.
              sourceId: initialTask.originalId || initialTask.id,
              values: values,
              value: values[values.length - 1],
              distribution: "linear",
              startTime: startTime,
              endTime: now,
              timestamp: now,
            };
    
            if (dispatcher.socket?.connected) {
              dispatcher.socket.emit("data_stream", payload);
            }
          }, 50);
    
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

