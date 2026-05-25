/* eslint-disable react-refresh/only-export-components */
import React, {
    useState,
    useEffect,
    useRef,
} from "react";
import { ColorPicker } from "../../../utils/Shared";
import { useAdapter } from "../hooks/useAdapter";
import { getConfig } from "../utils/configUtils";

// ==========================================
// 3. GENERIC SENSOR TEMPLATE
// ==========================================
const GenericSensorWidget = ({
  task,
  isConfigMode,
  onUpdateTask,
  streamBuffers,
  sourcePlugin
}) => {
  const adapterRef = useRef(null);
  const [currentValue, setCurrentValue] = useState(0);
  const requestRef = useRef(null);

  // Start the adapter.
  useAdapter(task, adapterRef, sourcePlugin, { defaultType: 'SENSOR' });

  // Use requestAnimationFrame instead of setInterval.
  useEffect(() => {
    if (!streamBuffers) return;
    const taskId = task.originalId || task.id;
    const buffer = streamBuffers.get(taskId);
    if (!buffer) return;

    let lastTime = performance.now();

    const update = (time) => {
      // Throttle to roughly 20 FPS.
      if (time - lastTime >= 50) {
        const latest = buffer.getLatest?.();
        
        if (latest !== null && latest !== undefined) {
          // React will bail out internally if the value did not change.
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

  // Extract the display config.
  const config = getConfig(task);
  const displayValue = (currentValue * config.factor).toFixed(2);

  // Render.
  return (
    <div className="h-full flex flex-col items-center justify-center p-4 bg-slate-900">
      <div className="text-xs text-slate-500 uppercase mb-2 tracking-widest font-bold">
        {task.name}
      </div>
      <div 
        className="text-6xl font-mono font-bold drop-shadow-lg"
        style={{ color: task.color }}
      >
        {displayValue}
        <span className="text-2xl text-slate-600 ml-2">{config.unit}</span>
      </div>
    </div>
  );
};

export const GenericSensorTemplate = {
  id: "tpl_generic_sensor",
  name: "Generic Sensor Display",
  type: "UI_TEMPLATE",
  render: GenericSensorWidget,
};
