/* eslint-disable react-refresh/only-export-components */
import React, {
    useRef,
    useMemo,
    useCallback,
    useState,
} from "react";
import { Icons, COLOR_PALETTE } from "../../../utils/Shared";
import dispatcher from "../../../services/DispatcherClient";
import { useScopeCanvas } from "../hooks/useScopeCanvas";
import { Draggable } from "../../../components/Draggable";
import ChannelMenu from "./ChannelMenu";
import TriggerMenu from "./TriggerMenu";
import { detectPeriod } from "../../../utils/fftProcessing";

const ScopeGraphWidget = ({
  task,
  isConfigMode,
  streamBuffers,
  onUpdateTask,
}) => {
  const canvasRef = useRef(null);
  const channelAnchorRef = useRef(null);
  const triggerAnchorRef = useRef(null);
  const [stats, setStats] = useState({});
  const [channelMenuOpen, setChannelMenuOpen] = useState(false);
  const [triggerMenuOpen, setTriggerMenuOpen] = useState(false);
  const [uiSettings, setUiSettings] = useState({
      isOverlayVisible: task.config?.isOverlayVisible ?? true,
      isPaused: task.config?.isPaused ?? false,
      showUncertaintyBand: task.config?.showUncertaintyBand ?? false,
  });
  const [overlayResetToken, setOverlayResetToken] = useState(0);
  const [rawCaptureAwaiting, setRawCaptureAwaiting] = useState(false);

  const updateConfig = useCallback((updates) => {
    const newConfig = { ...task.config, ...updates };
    onUpdateTask({ ...task, config: newConfig });
  }, [task, onUpdateTask]);

  const updateUiSetting = useCallback((keyOrObj, value) => {
      if (typeof keyOrObj === 'object') {
          setUiSettings(s => ({ ...s, ...keyOrObj }));
          updateConfig(keyOrObj);
      } else {
          setUiSettings(s => ({ ...s, [keyOrObj]: value }));
          updateConfig({ [keyOrObj]: value });
      }
  }, [updateConfig]);

  const singleSource = task.config?.singleSource;

  const sources = useMemo(() => {
    // In single-source mode, use only the task's own stream as input.
    if (singleSource) {
      return [{
        id: task.originalId || task.id,
        name: task.name,
        color: task.color,
        config: task.config,
        providerId: task.providerId,
        originalId: task.originalId,
        actions: task.actions || [],
      }];
    }
    const s = [];
    if (task.inputs?.source) s.push(task.inputs.source);
    if (task.extraChannels) s.push(...task.extraChannels);
    // Ensure unique sources by ID (avoid duplicate rendering / ghost traces)
    return Array.from(new Map(s.map((src) => [src?.id, src])).values());
  }, [task, singleSource]);

  // --- HOOKS ---
  const { centerTriggerInView } = useScopeCanvas(
    canvasRef,
    sources,
    streamBuffers,
    task,
    uiSettings,
    setStats,
    updateUiSetting,
    rawCaptureAwaiting,
    setRawCaptureAwaiting,
    () => setOverlayResetToken((prev) => prev + 1),
  );

  const handleAction = useCallback((source, actionId) => {
    if (!source) return;

    // Special handling for RAW capture: clear buffers and await data.
    if (actionId === 'START_RAW') {
      const sourceId = source.originalId || source.id;
      const buf = streamBuffers?.get(sourceId);
      if (buf) buf.clear();

      if (uiSettings.isPaused) {
        updateUiSetting('isPaused', false);
      }
      setRawCaptureAwaiting(true);
    }

    const providerId = source.config?.providerId || source.providerId;
    const target = providerId || `prov_${source.originalId || source.id}`;
    dispatcher.sendControlCommand(target, { action: actionId });
  }, [streamBuffers, uiSettings.isPaused, updateUiSetting]);

  const handleAutoset = useCallback(() => {
    // Use channel 1 (first source) for period detection.
    const ch1 = sources[0];
    if (!ch1) { console.warn('[Autoset] No source channel found'); return; }
    const buf = streamBuffers?.get(ch1.id) || streamBuffers?.get(ch1.originalId);
    if (!buf || buf.length() < 20) return;

    const data = buf.slice(-Infinity, Infinity);
    const period = detectPeriod(data);

    // Batch all config changes into a single update to avoid stale-state overwrites.
    const updates = {};
    if (period && period > 0) {
      updates.timeWindow = (period * 3) / 1000;
      console.log('[Autoset] period:', period.toFixed(3), 'ms → timeWindow:', updates.timeWindow.toFixed(4), 's');
    }

    // Autoscale Y based on visible data range
    let globalMin = Infinity, globalMax = -Infinity;
    data.forEach(p => {
      if (p.v < globalMin) globalMin = p.v;
      if (p.v > globalMax) globalMax = p.v;
    });
    if (globalMin !== Infinity && globalMax !== -Infinity) {
      let range = globalMax - globalMin;
      if (range === 0) range = globalMax === 0 ? 2 : Math.abs(globalMax);
      const pad = range * 0.1;
      let yMin = globalMin - pad;
      let yMax = globalMax + pad;

      // If trigger is configured, center Y on trigger level
      if (task.config?.trigger) {
        const lvl = task.config.trigger.level ?? 0;
        const halfRange = (yMax - yMin) / 2;
        yMin = lvl - halfRange;
        yMax = lvl + halfRange;
      }
      updates.yMin = yMin;
      updates.yMax = yMax;
    }

    setUiSettings(s => ({ ...s, ...updates }));
    onUpdateTask({ ...task, config: { ...task.config, ...updates } });

    // Center trigger in the view after autoset (pass freshly computed Y range)
    centerTriggerInView(updates.yMin, updates.yMax);
  }, [sources, streamBuffers, task, onUpdateTask, centerTriggerInView]);

  const exportScopeData = () => {
      const payload = {
          exportedAt: Date.now(),
          sources: {},
      };

      sources.forEach((s) => {
          const buf = streamBuffers?.get(s.id) || streamBuffers?.get(s.originalId);
          if (!buf) return;
          payload.sources[s.id] = {
              name: s.name,
              data: buf.getData(),
          };
      });

      const blob = new Blob([JSON.stringify(payload, null, 2)], {
          type: 'application/json',
      });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `scope-data-${Date.now()}.json`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
  };

  // --- HANDLER ---
  const handleDragOver = (e) => {
    e.preventDefault();
    e.stopPropagation();
  };
  const handleDrop = (e) => {
    e.preventDefault();
    e.stopPropagation();
    try {
      const droppedTask = JSON.parse(e.dataTransfer.getData("task"));
      
      if (droppedTask.type === 'TRIGGER') {
        onUpdateTask({ 
          ...task, 
          config: { 
            ...task.config, 
            trigger: { 
              mode: droppedTask.config.mode, 
              level: droppedTask.config.level || 0,
              channelId: sources[0]?.id || null
            } 
          } 
        });
        return;
      }

      if (droppedTask.id === task.id || sources.find(s => s.id === droppedTask.id)) return;
      const newInputs = !task.inputs?.source ? { ...task.inputs, source: droppedTask } : task.inputs;
      const newExtra = task.inputs?.source ? [...(task.extraChannels || []), droppedTask] : (task.extraChannels || []);
      onUpdateTask({ ...task, inputs: newInputs, extraChannels: newExtra });
    } catch (error) {
      console.error("Error handling drop in Scope:", error);
    }
  };

  const updateSourceMeta = useCallback((sourceId, key, value) => {
    // In single-source mode the task itself is the source.
    if (singleSource) {
      const updates = { ...task, [key]: value };
      onUpdateTask(updates);
      const targetProvider = task.providerId || task.originalId || task.id;
      dispatcher.sendControlCommand(`prov_${targetProvider}`, {
        action: "update_meta", payload: { [key]: value },
      });
      return;
    }

    const isPrimary = task.inputs?.source?.id === sourceId;
    let updatedSource;
    if (isPrimary) {
        updatedSource = { ...task.inputs.source, [key]: value };
    } else {
        const source = task.extraChannels?.find(c => c.id === sourceId);
        if (source) updatedSource = { ...source, [key]: value };
    }
    if (!updatedSource) return;

    const newInputs = isPrimary ? { ...task.inputs, source: updatedSource } : task.inputs;
    const newExtra = isPrimary ? task.extraChannels : task.extraChannels.map(c => c.id === sourceId ? updatedSource : c);
    onUpdateTask({ ...task, inputs: newInputs, extraChannels: newExtra });

    dispatcher.sendControlCommand(`prov_${updatedSource.originalId || updatedSource.id}`, {
      action: "update_meta", payload: { [key]: value },
    });
  }, [task, onUpdateTask, singleSource]);

  const removeSource = (sourceId) => {
    const newInputs = task.inputs?.source?.id === sourceId ? { ...task.inputs, source: null } : task.inputs;
    const newExtra = (task.extraChannels || []).filter(c => c.id !== sourceId);
    onUpdateTask({ ...task, inputs: newInputs, extraChannels: newExtra });
  };

  const assignTriggerChannel = useCallback((channelId) => {
    if (!task.config?.trigger) return;
    updateUiSetting({ trigger: { ...task.config.trigger, channelId } });
  }, [task.config, updateUiSetting]);

  // --- RENDER ---
  if (isConfigMode) {
    return (
      <div className="p-4 bg-slate-900 h-full overflow-y-auto custom-scrollbar">
        <div className="mb-6 border-b border-slate-800 pb-4">
          <div className="text-xs font-bold text-slate-500 uppercase mb-3 flex items-center gap-2"><Icons.Settings size={14} /> Axis Configuration</div>
          <div className="mb-3">
            <label className="text-xs text-slate-400 block mb-1">Timebase (X-Axis)</label>
            <select value={task.config?.timeWindow || 10} onChange={(e) => updateConfig({ timeWindow: Number(e.target.value) })} className="w-full bg-slate-950 text-slate-200 text-xs p-2 rounded border border-slate-700 focus:border-blue-500 outline-none">
              {[1, 2, 5, 10, 20, 30, 60].map(t => <option key={t} value={t}>{t} Second{t > 1 && 's'}</option>)}
            </select>
          </div>
          <div className="grid grid-cols-2 gap-2">
            {['yMin', 'yMax'].map(key => (
              <div key={key}>
                <label className="text-xs text-slate-400 block mb-1">{key === 'yMin' ? 'Y-Min' : 'Y-Max'}</label>
                <input type="number" step="any" value={task.config?.[key] ?? (key === 'yMin' ? -5 : 5)} onChange={(e) => updateConfig({ [key]: Number(e.target.value) })} className="w-full bg-slate-950 text-slate-200 text-xs p-2 rounded border border-slate-700 focus:border-blue-500 outline-none disabled:bg-slate-800" />
              </div>
            ))}
          </div>
        </div>

        {task.config?.trigger && (
          <div className="mb-6 border-b border-slate-800 pb-4">
            <div className="flex justify-between items-center mb-3">
              <div className="text-xs font-bold text-yellow-500 uppercase flex items-center gap-2"><Icons.Target size={14} /> Trigger</div>
              <button onClick={() => updateConfig({ trigger: null })} className="text-slate-500 hover:text-red-400 hover:bg-red-900/30 p-1 rounded transition-colors"><Icons.Trash2 size={14} /></button>
            </div>
            <div className="grid grid-cols-2 gap-2 mb-2">
              <div>
                <label className="text-[10px] text-slate-400 block mb-1">Mode</label>
                <select value={task.config.trigger.mode} onChange={(e) => updateConfig({ trigger: { ...task.config.trigger, mode: e.target.value }})} className="w-full bg-slate-950 text-slate-200 text-xs p-1.5 rounded border border-slate-700 outline-none focus:border-blue-500">
                  <option value="rising">Rising Edge</option>
                  <option value="falling">Falling Edge</option>
                  <option value="level">Level</option>
                </select>
              </div>
              <div>
                <label className="text-[10px] text-slate-400 block mb-1">Level</label>
                <input type="number" step="any" value={task.config.trigger.level} onChange={(e) => updateConfig({ trigger: { ...task.config.trigger, level: Number(e.target.value) }})} className="w-full bg-slate-950 text-slate-200 text-xs p-1.5 rounded border border-slate-700 outline-none focus:border-blue-500" />
              </div>
            </div>
            <div>
              <label className="text-[10px] text-slate-400 block mb-1">Channel</label>
              <select value={task.config.trigger.channelId || ''} onChange={(e) => updateConfig({ trigger: { ...task.config.trigger, channelId: e.target.value }})} className="w-full bg-slate-950 text-slate-200 text-xs p-1.5 rounded border border-slate-700 outline-none focus:border-blue-500">
                {sources.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
              </select>
            </div>
            <div className="mt-2">
              <label className="text-[10px] text-slate-400 block mb-1">Pretrigger (% vom neuesten Wert)</label>
              <input type="number" min="0" max="100" step="1" value={task.config.trigger.pretrigger ?? 5} onChange={(e) => updateConfig({ trigger: { ...task.config.trigger, pretrigger: Math.max(0, Math.min(100, Number(e.target.value))) }})} className="w-full bg-slate-950 text-slate-200 text-xs p-1.5 rounded border border-slate-700 outline-none focus:border-blue-500" />
            </div>
          </div>
        )}

        {!singleSource && (
          <>
            <div className="text-xs font-bold text-slate-500 uppercase mb-4 flex items-center gap-2"><Icons.Layers size={14} /> Assigned Channels</div>
            {sources.length === 0 && <div className="text-xs text-slate-600 italic">No channels connected.</div>}
            <div className="space-y-3">
              {sources.map(s => (
                <div key={s.id} className="bg-slate-950 p-3 rounded-lg border border-slate-800">
                  <div className="flex justify-between items-center mb-3">
                    <input type="text" value={s.name} onChange={(e) => updateSourceMeta(s.id, "name", e.target.value)} className="bg-slate-900 text-xs font-bold text-slate-300 px-2 py-1 rounded border border-slate-700 w-2/3 focus:outline-none focus:border-blue-500" />
                    <button onClick={() => removeSource(s.id)} className="text-slate-500 hover:text-red-400 hover:bg-red-900/30 p-1.5 rounded transition-colors" title="Remove Channel"><Icons.Trash2 size={14} /></button>
                  </div>
                  <div className="flex gap-1.5 flex-wrap">{COLOR_PALETTE.map(c => <button key={c} onClick={() => updateSourceMeta(s.id, "color", c)} className={`w-5 h-5 rounded-full border-2 transition-transform hover:scale-110 ${s.color === c ? "border-white scale-110 shadow-lg" : "border-transparent"}`} style={{ backgroundColor: c }} title={`Set color ${c}`} />)}</div>
                </div>
              ))}
            </div>
          </>
        )}
      </div>
    );
  }

  if (sources.length === 0) {
    return (
      <div onDragOver={handleDragOver} onDrop={handleDrop} className="h-full flex items-center justify-center border-2 border-dashed border-slate-700 rounded bg-slate-950/30 hover:border-slate-600 transition-colors">
        <div className="text-center text-slate-500 p-4">
          <Icons.Inbox className="mx-auto mb-2 opacity-50" size={32} />
          <p className="text-xs font-bold uppercase tracking-widest">Drop Task Here</p>
          <p className="text-[10px] text-slate-600 mt-1">Drag a sensor to display its value</p>
        </div>
      </div>
    );
  }

  return (
    <div onDragOver={handleDragOver} onDrop={handleDrop} className="h-full w-full bg-slate-950 relative group overflow-hidden">
      <canvas ref={canvasRef} className="w-full h-full block" />

      {rawCaptureAwaiting && (
        <div className="absolute inset-0 flex items-center justify-center pointer-events-none z-10">
          <div className="bg-amber-500/10 border border-amber-500/30 rounded-lg px-4 py-3 backdrop-blur-sm text-center">
            <Icons.Camera className="mx-auto mb-1 text-amber-400 animate-pulse" size={24} />
            <p className="text-xs font-bold text-amber-400 uppercase tracking-widest">RAW Capture</p>
            <p className="text-[10px] text-amber-500/70 mt-0.5">WiFi off &mdash; measuring...</p>
          </div>
        </div>
      )}

      {/* Channel indicator — click to open the channel menu */}
      {sources.length > 0 && (
        <div className="absolute top-2 left-2 z-40">
          <div className="flex items-center gap-2">
            <button
              ref={channelAnchorRef}
              onClick={() => {
                setChannelMenuOpen(prev => !prev);
                setTriggerMenuOpen(false);
              }}
              className={`flex items-center gap-1.5 px-2 py-1 rounded-md text-[10px] font-bold uppercase tracking-wider transition-all ${
                channelMenuOpen
                  ? 'bg-slate-700 text-slate-200 shadow-lg'
                  : 'bg-slate-900/60 text-slate-400 hover:bg-slate-800 hover:text-slate-200'
              }`}
              title="Open channel menu"
            >
              <div className="flex items-center gap-0.5">
                {sources.slice(0, 4).map(s => (
                  <div key={s.id} className="w-2 h-2 rounded-full ring-1 ring-black/30" style={{ backgroundColor: s.color }} />
                ))}
                {sources.length > 4 && <span className="text-slate-500 ml-0.5">+{sources.length - 4}</span>}
              </div>
              <span>{sources.length} CH</span>
              <Icons.ChevronDown size={10} className={`transition-transform ${channelMenuOpen ? 'rotate-180' : ''}`} />
            </button>

            {task.config?.trigger && (
              <button
                ref={triggerAnchorRef}
                onClick={() => {
                  setTriggerMenuOpen(prev => !prev);
                  setChannelMenuOpen(false);
                }}
                className={`flex items-center gap-1.5 px-2 py-1 rounded-md text-[10px] font-bold uppercase tracking-wider transition-all ${
                  triggerMenuOpen
                    ? 'bg-slate-700 text-slate-200 shadow-lg'
                    : 'bg-slate-900/60 text-slate-400 hover:bg-slate-800 hover:text-slate-200'
                }`}
                title="Open trigger menu"
              >
                <Icons.Target size={10} />
                <span className="truncate max-w-[90px]">{task.config.trigger.mode || 'trigger'}</span>
                <Icons.ChevronDown size={10} className={`transition-transform ${triggerMenuOpen ? 'rotate-180' : ''}`} />
              </button>
            )}
          </div>

          {channelMenuOpen && (
            <ChannelMenu
              sources={sources}
              onRemoveSource={removeSource}
              onColorChange={(sourceId, color) => updateSourceMeta(sourceId, "color", color)}
              onAction={handleAction}
              rawCaptureAwaiting={rawCaptureAwaiting}
              singleSource={singleSource}
              onClose={() => setChannelMenuOpen(false)}
              anchorRef={channelAnchorRef}
            />
          )}

          {triggerMenuOpen && (
            <TriggerMenu
              trigger={task.config?.trigger}
              channels={sources}
              onAssignChannel={assignTriggerChannel}
              onClose={() => setTriggerMenuOpen(false)}
              anchorRef={triggerAnchorRef}
            />
          )}
        </div>
      )}

      <div className="absolute top-2 right-2 flex items-center gap-2">
          <button onClick={() => updateUiSetting('isPaused', !uiSettings.isPaused)} className="p-1.5 text-slate-400 bg-slate-900/50 rounded-full hover:bg-slate-800 hover:text-white transition-all opacity-0 group-hover:opacity-100" title="Pause/Resume">
              {uiSettings.isPaused ? <Icons.Play size={14} /> : <Icons.Pause size={14} />}
          </button>
          <button onClick={() => updateUiSetting('isOverlayVisible', !uiSettings.isOverlayVisible)} className="p-1.5 text-slate-400 bg-slate-900/50 rounded-full hover:bg-slate-800 hover:text-white transition-all opacity-0 group-hover:opacity-100" title="Toggle overlay">
              <Icons.Eye size={14} className={`${!uiSettings.isOverlayVisible ? 'hidden' : 'block'}`} />
              <Icons.EyeOff size={14} className={`${!uiSettings.isOverlayVisible ? 'block' : 'hidden'}`} />
          </button>
            <button onClick={() => updateUiSetting('showUncertaintyBand', !uiSettings.showUncertaintyBand)} className="p-1.5 text-slate-400 bg-slate-900/50 rounded-full hover:bg-slate-800 hover:text-white transition-all opacity-0 group-hover:opacity-100" title="Toggle uncertainty band">
              <Icons.Sigma size={14} className={`${uiSettings.showUncertaintyBand ? 'text-cyan-300' : ''}`} />
            </button>
          <button onClick={handleAutoset} className="p-1.5 text-slate-400 bg-slate-900/50 rounded-full hover:bg-slate-800 hover:text-white transition-all opacity-0 group-hover:opacity-100" title="Autoset">
              <Icons.Activity size={14} />
          </button>
          <button onClick={() => exportScopeData()} className="p-1.5 text-slate-400 bg-slate-900/50 rounded-full hover:bg-slate-800 hover:text-white transition-all opacity-0 group-hover:opacity-100" title="Download scope data">
              <Icons.Download size={14} />
          </button>
      </div>

      {uiSettings.isOverlayVisible && sources.length > 0 && (
          <div className="absolute top-8 right-2 pointer-events-none">
              <Draggable resetTrigger={overlayResetToken}>
                  <div className="flex flex-col gap-2 pointer-events-auto">
                      {sources.map(s => {
                          const stat = stats[s.id];
                          if (!stat) return null;
                          return (
                              <div key={s.id} className="bg-slate-900/80 backdrop-blur border border-slate-700 p-2 rounded shadow-lg min-w-[120px]">
                                  <div className="flex items-center gap-2 mb-1">
                                      <div className="w-2 h-2 rounded-full" style={{backgroundColor: s.color}}></div>
                                      <span className="text-[10px] font-bold uppercase text-slate-300">{s.name}</span>
                                  </div>
                                  <div className="grid grid-cols-2 gap-x-4 gap-y-0 text-[10px] text-slate-400 font-mono">
                                      <span>Now:</span> <span className="text-white text-right">{stat.current?.toFixed(2)}</span>
                                      <span>Min:</span> <span className="text-right">{stat.min?.toFixed(2)}</span>
                                      <span>Max:</span> <span className="text-right">{stat.max?.toFixed(2)}</span>
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

export const ScopeGraphPlugin = {
  id: "tpl_scope",
  name: "Scope Graph",
  type: "UI_TEMPLATE",
  render: ScopeGraphWidget,
};
