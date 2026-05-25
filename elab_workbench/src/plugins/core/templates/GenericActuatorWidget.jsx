/* eslint-disable react-refresh/only-export-components */
import React, {
    useState,
    useRef,
    useCallback,
} from "react";
import { Icons, ColorPicker } from "../../../utils/Shared";
import { useAdapter } from "../hooks/useAdapter";
import { getConfig } from "../utils/configUtils";

// ============================================================================
// 4. GENERIC ACTUATOR TEMPLATE
// ============================================================================

const GenericActuatorWidget = ({
  task,
  isConfigMode,
  onUpdateTask,
  sourcePlugin,
}) => {
  const adapterRef = useRef(null);
  const [value, setValue] = useState(task.config?.value || 0);

  // Adapter starten
  useAdapter(task, adapterRef, sourcePlugin, { defaultType: "ACTUATOR" });

  // Change Handler
  const handleChange = useCallback(
    (newValue) => {
      setValue(newValue);

      if (adapterRef.current) {
        adapterRef.current.sendControl({ value: newValue });
      }

      onUpdateTask({
        ...task,
        config: { ...task.config, value: newValue },
      });
    },
    [task, onUpdateTask],
  );

  // Config Mode
  if (isConfigMode) {
    return <ColorPicker task={task} onUpdateTask={onUpdateTask} />;
  }

  // Config extrahieren
  const config = getConfig(task);

  // Render
  return (
    <div className="h-full flex flex-col p-4 bg-slate-900">
      {/* Header */}
      <div className="flex items-center gap-2 mb-4">
        <Icons.Zap style={{ color: task.color }} size={20} />
        <span className="text-sm font-bold text-slate-300">{task.name}</span>
      </div>

      {/* Control */}
      <div className="flex-1 flex flex-col justify-center">
        {/* Value Display */}
        <div className="text-center mb-4">
          <div
            className="text-5xl font-mono font-bold"
            style={{ color: task.color }}
          >
            {value.toFixed(1)}
            <span className="text-2xl text-slate-600 ml-2">{config.unit}</span>
          </div>
        </div>

        {/* Slider */}
        <input
          type="range"
          min={config.min}
          max={config.max}
          step={config.step}
          value={value}
          onChange={(e) => handleChange(Number(e.target.value))}
          className="w-full h-2 bg-slate-800 rounded-lg appearance-none cursor-pointer accent-blue-500"
        />

        {/* Range Labels */}
        <div className="flex justify-between text-xs text-slate-600 mt-2">
          <span>
            {config.min}
            {config.unit}
          </span>
          <span>
            {config.max}
            {config.unit}
          </span>
        </div>
      </div>
    </div>
  );
};

export const GenericActuatorTemplate = {
  id: "tpl_generic_actuator",
  name: "Generic Actuator Control",
  type: "UI_TEMPLATE",
  render: GenericActuatorWidget,
};
