/* eslint-disable react-refresh/only-export-components */
import React, { useCallback, useMemo } from "react";
import { Icons, COLOR_PALETTE } from "../../../utils/Shared";
import dispatcher from "../../../services/DispatcherClient";

const FFT_SIZE_OPTIONS = [256, 512, 1024, 2048, 4096, 8192, 16384, 32768, 65536, 131072];

const SpectrumConfigWidget = ({ task, onUpdateTask }) => {
  const updateConfig = useCallback(
    (key, value) => {
      const newConfig = { ...task.config, [key]: value };
      onUpdateTask({ ...task, config: newConfig });
    },
    [task, onUpdateTask],
  );

  const sources = useMemo(() => {
    const s = [];
    if (task.inputs?.source) s.push(task.inputs.source);
    if (task.extraChannels) s.push(...task.extraChannels);
    return Array.from(new Map(s.map((src) => [src?.id, src])).values());
  }, [task]);

  const removeSource = (sourceId) => {
    const newInputs =
      task.inputs?.source?.id === sourceId
        ? { ...task.inputs, source: null }
        : task.inputs;
    const newExtra = (task.extraChannels || []).filter(
      (c) => c.id !== sourceId,
    );
    onUpdateTask({ ...task, inputs: newInputs, extraChannels: newExtra });
  };

  const updateSourceMeta = useCallback(
    (sourceId, key, value) => {
      const isPrimary = task.inputs?.source?.id === sourceId;
      let updatedSource;
      if (isPrimary) {
        updatedSource = { ...task.inputs.source, [key]: value };
      } else {
        const source = task.extraChannels?.find((c) => c.id === sourceId);
        if (source) updatedSource = { ...source, [key]: value };
      }
      if (!updatedSource) return;

      const newInputs = isPrimary
        ? { ...task.inputs, source: updatedSource }
        : task.inputs;
      const newExtra = isPrimary
        ? task.extraChannels
        : task.extraChannels.map((c) =>
            c.id === sourceId ? updatedSource : c,
          );
      onUpdateTask({ ...task, inputs: newInputs, extraChannels: newExtra });

      dispatcher.sendControlCommand(
        `prov_${updatedSource.originalId || updatedSource.id}`,
        {
          action: "update_meta",
          payload: { [key]: value },
        },
      );
    },
    [task, onUpdateTask],
  );

  // --- Drop handler (only accept time-domain sensor signals) ---
  const handleDragOver = (e) => {
    e.preventDefault();
    e.stopPropagation();
  };
  const handleDrop = (e) => {
    e.preventDefault();
    e.stopPropagation();
    try {
      const dropped = JSON.parse(e.dataTransfer.getData("task"));
      if (dropped.type === "MEASURE") {
        console.warn(
          "[Spectrum] Rejected drop – only time-domain signals (SENSOR/ACTUATOR) are accepted.",
        );
        return;
      }
      if (dropped.id === task.id || sources.find((s) => s.id === dropped.id))
        return;
      const newInputs = !task.inputs?.source
        ? { ...task.inputs, source: dropped }
        : task.inputs;
      const newExtra = task.inputs?.source
        ? [...(task.extraChannels || []), dropped]
        : task.extraChannels || [];
      onUpdateTask({ ...task, inputs: newInputs, extraChannels: newExtra });
    } catch (err) {
      console.error("Error handling drop in SpectrumConfig:", err);
    }
  };

  return (
    <div
      onDragOver={handleDragOver}
      onDrop={handleDrop}
      className="p-4 bg-slate-900 h-full overflow-y-auto custom-scrollbar"
    >
      <div className="mb-6 border-b border-slate-800 pb-4">
        <div className="text-xs font-bold text-slate-500 uppercase mb-3 flex items-center gap-2">
          <Icons.Settings size={14} /> Spectrum Configuration
        </div>

        <div className="flex items-center gap-2 mb-3 bg-slate-800 p-2 rounded">
          <input
            type="checkbox"
            id={`autoscale-${task.id}`}
            checked={task.config?.autoscaleY ?? true}
            onChange={(e) => updateConfig("autoscaleY", e.target.checked)}
            className="form-checkbox h-4 w-4 bg-slate-700 border-slate-600 text-blue-500 rounded focus:ring-blue-500"
          />
          <label
            htmlFor={`autoscale-${task.id}`}
            className="text-xs text-slate-300 font-bold"
          >
            Enable Y-Axis Autoscale
          </label>
        </div>

        <div className="flex items-center gap-2 mb-3 bg-slate-800 p-2 rounded">
          <input
            type="checkbox"
            id={`overlay-${task.id}`}
            checked={task.config?.isOverlayVisible ?? true}
            onChange={(e) => updateConfig("isOverlayVisible", e.target.checked)}
            className="form-checkbox h-4 w-4 bg-slate-700 border-slate-600 text-blue-500 rounded focus:ring-blue-500"
          />
          <label
            htmlFor={`overlay-${task.id}`}
            className="text-xs text-slate-300 font-bold"
          >
            Show Stats Overlay
          </label>
        </div>

        <div className="mb-3">
          <label className="text-xs text-slate-400 block mb-1">
            FFT Buffer Size
          </label>
          <select
            value={task.config?.fftSize || 4096}
            onChange={(e) => updateConfig("fftSize", Number(e.target.value))}
            className="w-full bg-slate-950 text-slate-200 text-xs p-2 rounded border border-slate-700 focus:border-blue-500 outline-none"
          >
            {FFT_SIZE_OPTIONS.map((s) => (
              <option key={s} value={s}>
                {s >= 32768 ? `${s / 1024}k samples (WebGPU)` : `${s} samples`}
              </option>
            ))}
          </select>
          {(task.config?.fftSize || 4096) >= 32768 && (
            <p className="text-[10px] text-violet-400 mt-1">
              WebGPU-accelerated – GPU computes FFT off main thread
            </p>
          )}
        </div>

        <div className="mb-3">
          <label className="text-xs text-slate-400 block mb-1">
            Max Frequency (0 = auto / Nyquist)
          </label>
          <div className="flex items-center gap-2">
            <input
              type="number"
              value={task.config?.maxFreq || 0}
              min="0"
              step="100"
              onChange={(e) =>
                updateConfig("maxFreq", Math.max(0, Number(e.target.value)))
              }
              className="w-full bg-slate-950 text-slate-200 text-xs p-2 rounded border border-slate-700 focus:border-blue-500 outline-none"
            />
            <span className="text-xs text-slate-500 whitespace-nowrap">Hz</span>
          </div>
        </div>
      </div>

      <div className="text-xs font-bold text-slate-500 uppercase mb-4 flex items-center gap-2">
        <Icons.Layers size={14} /> Assigned Channels
      </div>
      {sources.length === 0 && (
        <div className="text-xs text-slate-600 italic">
          No channels connected. Drag a time-domain sensor here.
        </div>
      )}
      <div className="space-y-3">
        {sources.map((s) => (
          <div
            key={s.id}
            className="bg-slate-950 p-3 rounded-lg border border-slate-800"
          >
            <div className="flex justify-between items-center mb-3">
              <input
                type="text"
                value={s.name}
                onChange={(e) =>
                  updateSourceMeta(s.id, "name", e.target.value)
                }
                className="bg-slate-900 text-xs font-bold text-slate-300 px-2 py-1 rounded border border-slate-700 w-2/3 focus:outline-none focus:border-blue-500"
              />
              <button
                onClick={() => removeSource(s.id)}
                className="text-slate-500 hover:text-red-400 hover:bg-red-900/30 p-1.5 rounded transition-colors"
                title="Remove Channel"
              >
                <Icons.Trash2 size={14} />
              </button>
            </div>
            <div className="flex gap-1.5 flex-wrap">
              {COLOR_PALETTE.map((c) => (
                <button
                  key={c}
                  onClick={() => updateSourceMeta(s.id, "color", c)}
                  className={`w-5 h-5 rounded-full border-2 transition-transform hover:scale-110 ${s.color === c ? "border-white scale-110 shadow-lg" : "border-transparent"}`}
                  style={{ backgroundColor: c }}
                  title={`Set color ${c}`}
                />
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};

export const SpectrumConfigPlugin = {
  id: "tpl_spectrum_config",
  name: "Spectrum Config",
  type: "UI_TEMPLATE",
  render: SpectrumConfigWidget,
};
