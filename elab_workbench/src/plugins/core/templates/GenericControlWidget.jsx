/* eslint-disable react-refresh/only-export-components */
import React, { useState, useRef, useCallback } from "react";
import { Icons, ColorPicker } from "../../../utils/Shared";
import { useAdapter } from "../hooks/useAdapter";
import { getConfig } from "../utils/configUtils";

// ============================================================================
// GENERIC CONTROL TEMPLATE
// ============================================================================

const GenericControlWidget = ({
  task,
  isConfigMode,
  onUpdateTask,
  sourcePlugin,
}) => {
  const adapterRef = useRef(null);
  const [active, setActive] = useState(task.config?.active ?? false);

  // Start the adapter.
  useAdapter(task, adapterRef, sourcePlugin, { defaultType: "CONTROL" });

  // Toggle handler.
  const handleToggle = useCallback(() => {
    const next = !active;
    setActive(next);

    if (adapterRef.current) {
      adapterRef.current.sendControl({ active: next });
    }

    onUpdateTask({
      ...task,
      config: { ...task.config, active: next },
    });
  }, [active, task, onUpdateTask]);

  // Config mode.
  if (isConfigMode) {
    return <ColorPicker task={task} onUpdateTask={onUpdateTask} />;
  }

  const config = getConfig(task);

  return (
    <div className="h-full flex flex-col p-4 bg-slate-900">
      {/* Header */}
      <div className="flex items-center gap-2 mb-4">
        <Icons.Settings style={{ color: task.color }} size={20} />
        <span className="text-sm font-bold text-slate-300">{task.name}</span>
      </div>

      {/* Control */}
      <div className="flex-1 flex flex-col items-center justify-center">
        <button
          onClick={handleToggle}
          className={`w-20 h-20 rounded-full border-4 transition-colors ${
            active
              ? "border-green-500 bg-green-500/20"
              : "border-slate-600 bg-slate-800"
          }`}
        >
          <Icons.Zap
            size={32}
            className={`mx-auto ${active ? "text-green-400" : "text-slate-500"}`}
          />
        </button>
        <span className="mt-3 text-sm text-slate-400">
          {active ? "Active" : "Inactive"}
        </span>
        {config.unit && (
          <span className="mt-1 text-xs text-slate-600">{config.unit}</span>
        )}
      </div>
    </div>
  );
};

export const GenericControlTemplate = {
  id: "tpl_generic_control",
  name: "Generic Control",
  type: "UI_TEMPLATE",
  render: GenericControlWidget,
};
