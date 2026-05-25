/* eslint-disable react-refresh/only-export-components */
import React, {
  useRef,
  useMemo,
  useCallback,
  useState,
} from "react";
import { Icons } from "../../../utils/Shared";
import { useSpectrumCanvas } from "../hooks/useSpectrumCanvas";
import { Draggable } from "../../../components/Draggable";

const SpectrumWidget = ({
  task,
  isConfigMode,
  streamBuffers,
  onUpdateTask,
}) => {
  const canvasRef = useRef(null);
  const [stats, setStats] = useState({});

  const uiSettings = useMemo(() => ({
    isOverlayVisible: task.config?.isOverlayVisible ?? true,
    autoscaleY: task.config?.autoscaleY ?? true,
  }), [task.config?.isOverlayVisible, task.config?.autoscaleY]);

  const updateConfig = useCallback((key, value) => {
    const newConfig = { ...task.config, [key]: value };
    onUpdateTask({ ...task, config: newConfig });
  }, [task, onUpdateTask]);

  const sources = useMemo(() => {
    const s = [];
    if (task.inputs?.source) s.push(task.inputs.source);
    if (task.extraChannels) s.push(...task.extraChannels);
    return Array.from(new Map(s.map((src) => [src?.id, src])).values());
  }, [task]);

  useSpectrumCanvas(canvasRef, sources, streamBuffers, task, uiSettings, setStats);

  // Config is handled by SpectrumConfigWidget (separate view)
  if (isConfigMode) return null;

  // --- Drop handler (only accept time-domain sensor signals) ---
  const handleDragOver = (e) => { e.preventDefault(); e.stopPropagation(); };
  const handleDrop = (e) => {
    e.preventDefault();
    e.stopPropagation();
    try {
      const dropped = JSON.parse(e.dataTransfer.getData("task"));
      // Restrict input to time-domain signals (SENSOR type tasks).
      if (dropped.type === "MEASURE") {
        console.warn("[Spectrum] Rejected drop – only time-domain signals (SENSOR/ACTUATOR) are accepted.");
        return;
      }
      if (dropped.id === task.id || sources.find(s => s.id === dropped.id)) return;
      const newInputs = !task.inputs?.source
        ? { ...task.inputs, source: dropped }
        : task.inputs;
      const newExtra = task.inputs?.source
        ? [...(task.extraChannels || []), dropped]
        : (task.extraChannels || []);
      onUpdateTask({ ...task, inputs: newInputs, extraChannels: newExtra });
    } catch (err) {
      console.error("Error handling drop in Spectrum:", err);
    }
  };

  const exportSpectrumData = () => {
    const payload = { exportedAt: Date.now(), sources: {} };
    sources.forEach(s => {
      const buf = streamBuffers?.get(s.id) || streamBuffers?.get(s.originalId);
      if (!buf) return;
      payload.sources[s.id] = { name: s.name, data: buf.getData() };
    });
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `spectrum-data-${Date.now()}.json`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  // --- Empty state ---
  if (sources.length === 0) {
    return (
      <div onDragOver={handleDragOver} onDrop={handleDrop} className="h-full flex items-center justify-center border-2 border-dashed border-slate-700 rounded bg-slate-950/30 hover:border-slate-600 transition-colors">
        <div className="text-center text-slate-500 p-4">
          <Icons.BarChart2 className="mx-auto mb-2 opacity-50" size={32} />
          <p className="text-xs font-bold uppercase tracking-widest">Drop Signal Here</p>
          <p className="text-[10px] text-slate-600 mt-1">Drag a time-domain sensor to view its spectrum</p>
        </div>
      </div>
    );
  }

  // --- Display mode ---
  return (
    <div onDragOver={handleDragOver} onDrop={handleDrop} className="h-full w-full bg-slate-950 relative group overflow-hidden">
      <canvas ref={canvasRef} className="w-full h-full block" />

      {/* Channel indicators */}
      {sources.length > 0 && (
        <div className="absolute top-2 left-2 flex items-center gap-1 z-40">
          {sources.slice(0, 4).map(s => (
            <div key={s.id} className="w-2 h-2 rounded-full ring-1 ring-black/30" style={{ backgroundColor: s.color }} />
          ))}
          {sources.length > 4 && <span className="text-[10px] text-slate-500">+{sources.length - 4}</span>}
          <span className="text-[10px] font-bold text-slate-500 uppercase ml-1">{sources.length} CH</span>
        </div>
      )}

      {/* Toolbar */}
      <div className="absolute top-2 right-2 flex items-center gap-2">
        <button
          onClick={() => updateConfig("isOverlayVisible", !uiSettings.isOverlayVisible)}
          className="p-1.5 text-slate-400 bg-slate-900/50 rounded-full hover:bg-slate-800 hover:text-white transition-all opacity-0 group-hover:opacity-100"
          title="Toggle overlay"
        >
          <Icons.Eye size={14} className={!uiSettings.isOverlayVisible ? "hidden" : "block"} />
          <Icons.EyeOff size={14} className={!uiSettings.isOverlayVisible ? "block" : "hidden"} />
        </button>
        <button
          onClick={exportSpectrumData}
          className="p-1.5 text-slate-400 bg-slate-900/50 rounded-full hover:bg-slate-800 hover:text-white transition-all opacity-0 group-hover:opacity-100"
          title="Download spectrum data"
        >
          <Icons.Download size={14} />
        </button>
      </div>

      {/* Stats overlay */}
      {uiSettings.isOverlayVisible && sources.length > 0 && (
        <div className="absolute top-8 right-2 pointer-events-none">
          <Draggable>
            <div className="flex flex-col gap-2 pointer-events-auto">
              {sources.map(s => {
                const stat = stats[s.id];
                if (!stat) return null;
                return (
                  <div key={s.id} className="bg-slate-900/80 backdrop-blur border border-slate-700 p-2 rounded shadow-lg min-w-[140px]">
                    <div className="flex items-center gap-2 mb-1">
                      <div className="w-2 h-2 rounded-full" style={{ backgroundColor: s.color }} />
                      <span className="text-[10px] font-bold uppercase text-slate-300">{s.name}</span>
                    </div>
                    <div className="grid grid-cols-2 gap-x-4 gap-y-0 text-[10px] text-slate-400 font-mono">
                      <span>Peak:</span>
                      <span className="text-white text-right">
                        {stat.peakFreq >= 1000
                          ? `${(stat.peakFreq / 1000).toFixed(2)} kHz`
                          : `${stat.peakFreq?.toFixed(1)} Hz`}
                      </span>
                      <span>Mag:</span>
                      <span className="text-right">{stat.peakMag?.toFixed(3)}</span>
                      <span>Fs:</span>
                      <span className="text-right">
                        {stat.sampleRate >= 1000
                          ? `${(stat.sampleRate / 1000).toFixed(1)} kHz`
                          : `${stat.sampleRate?.toFixed(0)} Hz`}
                      </span>
                      <span>Δf:</span>
                      <span className="text-right">{stat.resolution?.toFixed(2)} Hz</span>
                    </div>
                  </div>
                );
              })}
            </div>
          </Draggable>
        </div>
      )}
    </div>
  );
};

export const SpectrumGraphPlugin = {
  id: "tpl_spectrum",
  name: "Spectrum Graph",
  type: "UI_TEMPLATE",
  render: SpectrumWidget,
};
