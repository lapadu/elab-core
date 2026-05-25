/* eslint-disable react-refresh/only-export-components */
import React, { useState, useEffect, useRef } from "react";
import { Icons, ColorPicker } from "../../../utils/Shared";
import { useAdapter } from "../hooks/useAdapter";
import { getConfig } from "../utils/configUtils";

// ============================================================================
// GENERIC GENERATOR TEMPLATE
// ============================================================================

const GenericGeneratorWidget = ({
  task,
  isConfigMode,
  onUpdateTask,
  streamBuffers,
  sourcePlugin,
}) => {
  const adapterRef = useRef(null);
  const [currentValue, setCurrentValue] = useState(0);
  const requestRef = useRef(null);

  // Start the adapter.
  useAdapter(task, adapterRef, sourcePlugin, { defaultType: "GENERATOR" });

  // Use requestAnimationFrame to read the latest value.
  useEffect(() => {
    if (!streamBuffers) return;
    const taskId = task.originalId || task.id;
    const buffer = streamBuffers.get(taskId);
    if (!buffer) return;

    let lastTime = performance.now();

    const update = (time) => {
      if (time - lastTime >= 50) {
        const latest = buffer.getLatest?.();
        if (latest !== null && latest !== undefined) {
          setCurrentValue(latest);
        }
        lastTime = time;
      }
      requestRef.current = requestAnimationFrame(update);
    };

    requestRef.current = requestAnimationFrame(update);
    return () => cancelAnimationFrame(requestRef.current);
  }, [streamBuffers, task]);

  // Config mode.
  if (isConfigMode) {
    return <ColorPicker task={task} onUpdateTask={onUpdateTask} />;
  }

  const config = getConfig(task);
  const displayValue = (currentValue * (config.factor || 1)).toFixed(2);

  return (
    <div className="h-full flex flex-col p-4 bg-slate-900">
      {/* Header */}
      <div className="flex items-center gap-2 mb-4">
        <Icons.Zap style={{ color: task.color }} size={20} />
        <span className="text-sm font-bold text-slate-300">{task.name}</span>
      </div>

      {/* Output display */}
      <div className="flex-1 flex flex-col items-center justify-center">
        <div className="text-xs text-slate-500 uppercase mb-2 tracking-widest">
          Output
        </div>
        <div
          className="text-5xl font-mono font-bold drop-shadow-lg"
          style={{ color: task.color }}
        >
          {displayValue}
          <span className="text-2xl text-slate-600 ml-2">{config.unit}</span>
        </div>
        {config.frequency && (
          <div className="mt-3 text-sm text-slate-400">
            {config.frequency} Hz
          </div>
        )}
      </div>
    </div>
  );
};

export const GenericGeneratorTemplate = {
  id: "tpl_generic_generator",
  name: "Generic Generator",
  type: "UI_TEMPLATE",
  render: GenericGeneratorWidget,
};
