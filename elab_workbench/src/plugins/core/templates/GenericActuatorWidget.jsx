/* eslint-disable react-refresh/only-export-components */
import React, {
    useState,
    useRef,
    useCallback,
    useEffect,
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
  streamBuffers,
  dispatcherClient,
}) => {
  const adapterRef = useRef(null);
  const [value, setValue] = useState(task.config?.value || 0);
  const sourceId = task.inputs?.source?.id || null;

  // Adapter starten (nur für virtuelle Tasks relevant)
  useAdapter(task, adapterRef, sourcePlugin, { defaultType: "ACTUATOR" });

  // Server-side routing: link the source to this actuator once, so the
  // dispatcher streams data directly to the hardware provider (no 20 Hz UI
  // round-trip). Virtual in-browser adapters keep the local path below.
  useEffect(() => {
    if (!sourceId || adapterRef.current || !dispatcherClient) return;
    const linkSourceId = task.inputs?.source?.originalId || task.inputs?.source?.id;
    if (!linkSourceId) return;
    const provId = task.providerId || `prov_${task.originalId || task.id}`;
    dispatcherClient.linkSource(linkSourceId, provId);
    return () => dispatcherClient.unlinkSource(linkSourceId, provId);
  }, [sourceId, dispatcherClient, task.providerId, task.id, task.originalId, task.inputs]);

  // Display feedback: mirror the source's latest value on screen. For real
  // hardware the dispatcher does the actual routing; only virtual adapters
  // still forward control locally here.
  useEffect(() => {
    if (!sourceId || !streamBuffers) return;

    const interval = setInterval(() => {
      const buffer = streamBuffers.get(sourceId) || streamBuffers.get(task.inputs?.source?.originalId);
      if (!buffer) return;

      const latest = buffer.getLatest?.();
      if (latest === undefined || latest === null) return;
      setValue(latest);

      // Virtual (in-browser) adapter: no server-side route exists, forward here.
      if (adapterRef.current) {
        adapterRef.current.sendControl({ value: latest });
      }
    }, 50);

    return () => clearInterval(interval);
  }, [sourceId, streamBuffers, task.inputs, task.id, task.originalId]);

  // Change Handler für manuelle Slider-Bedienung
  const handleChange = useCallback(
    (newValue) => {
      setValue(newValue);

      if (adapterRef.current) {
        adapterRef.current.sendControl({ value: newValue });
      } else if (dispatcherClient) {
        const provId = task.providerId || `prov_${task.originalId || task.id}`;
        dispatcherClient.sendControlCommand(provId, {
          action: 'set_value',
          payload: { value: newValue }
        });
      }

      onUpdateTask({
        ...task,
        config: { ...task.config, value: newValue },
      });
    },
    [task, onUpdateTask, dispatcherClient],
  );

  // --- Drag & Drop für Quelle ---
  const handleDragOver = (e) => {
    e.preventDefault();
    e.stopPropagation();
  };

  const handleDrop = (e) => {
    e.preventDefault();
    e.stopPropagation();
    try {
      const dataStr = e.dataTransfer.getData("task");
      if (!dataStr) return;
      const droppedTask = JSON.parse(dataStr);
      if (droppedTask.id === task.id) return;
      
      onUpdateTask({ ...task, inputs: { ...task.inputs, source: droppedTask } });
    } catch (err) {
      console.error(err);
    }
  };

  const removeSource = (e) => {
    e.stopPropagation();
    onUpdateTask({ ...task, inputs: { ...task.inputs, source: null } });
  };

  // Config Mode
  if (isConfigMode) {
    return <ColorPicker task={task} onUpdateTask={onUpdateTask} />;
  }

  // Config extrahieren
  const config = getConfig(task);

  // Render
  return (
    <div 
      className={`h-full flex flex-col p-4 bg-slate-900 transition-colors ${sourceId ? 'border-2 border-blue-500/30' : ''}`}
      onDragOver={handleDragOver}
      onDrop={handleDrop}
    >
      {/* Header */}
      <div className="flex items-center gap-2 mb-4 shrink-0">
        <Icons.Zap style={{ color: task.color }} size={20} />
        <span className="text-sm font-bold text-slate-300">{task.name}</span>
      </div>

      {/* Control */}
      <div className="flex-1 flex flex-col justify-center min-h-0">
        {/* Value Display */}
        <div className="text-center mb-4">
          <div
            className="text-5xl font-mono font-bold truncate"
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
          disabled={!!sourceId}
          className={`w-full h-2 bg-slate-800 rounded-lg appearance-none accent-blue-500 ${sourceId ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'}`}
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
        
        {/* Source Link Info */}
        <div className="mt-4 flex items-center justify-between text-xs bg-slate-950 p-2 rounded border border-slate-800 shrink-0">
          {task.inputs?.source ? (
            <>
              <div className="flex items-center gap-2 truncate pr-2">
                <Icons.Link size={14} className="text-blue-400 shrink-0" />
                <span className="text-slate-300 font-bold truncate">{task.inputs.source.name}</span>
              </div>
              <button onClick={removeSource} className="text-slate-500 hover:text-red-400 shrink-0">
                <Icons.X size={14} />
              </button>
            </>
          ) : (
            <div className="text-slate-500 flex items-center gap-2">
              <Icons.Inbox size={14} />
              <span>Drag Generator Here</span>
            </div>
          )}
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
