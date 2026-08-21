/* eslint-disable react-refresh/only-export-components */
import React, {
    useState,
    useEffect,
    useRef,
    useMemo,
    useCallback,
} from "react";
import { ColorPicker, Icons } from "../../../utils/Shared";
import { getConfig, getLatestValue } from "../utils/configUtils";
import dispatcher from "../../../services/DispatcherClient";

// ==========================================
// SI PREFIX AUTO-RANGE
// ==========================================

const SI_PREFIXES = [
  { exp: -12, symbol: "p" },
  { exp: -9,  symbol: "n" },
  { exp: -6,  symbol: "µ" },
  { exp: -3,  symbol: "m" },
  { exp: 0,   symbol: "" },
  { exp: 3,   symbol: "k" },
  { exp: 6,   symbol: "M" },
  { exp: 9,   symbol: "G" },
  { exp: 12,  symbol: "T" },
];

/**
 * Auto-select the best SI prefix for a given value.
 * Returns { scaled, prefix, exp } where scaled is the value divided by 10^exp.
 */
function autoRange(value) {
  const abs = Math.abs(value);
  if (abs === 0) return { scaled: 0, prefix: "", exp: 0 };

  for (let i = SI_PREFIXES.length - 1; i >= 0; i--) {
    if (abs >= Math.pow(10, SI_PREFIXES[i].exp)) {
      return {
        scaled: value / Math.pow(10, SI_PREFIXES[i].exp),
        prefix: SI_PREFIXES[i].symbol,
        exp: SI_PREFIXES[i].exp,
      };
    }
  }
  // Smaller than pico — use the smallest
  return {
    scaled: value / Math.pow(10, SI_PREFIXES[0].exp),
    prefix: SI_PREFIXES[0].symbol,
    exp: SI_PREFIXES[0].exp,
  };
}

/**
 * Apply a fixed SI prefix to the value.
 */
function fixedRange(value, prefixEntry) {
  return {
    scaled: value / Math.pow(10, prefixEntry.exp),
    prefix: prefixEntry.symbol,
    exp: prefixEntry.exp,
  };
}

/** Expanded uncertainty (k-scaled) in base units, or 0 when unavailable. */
function uncertaintyDelta(uncertainty) {
  if (!uncertainty || typeof uncertainty !== "object") return 0;
  const systematic = Number(uncertainty.systematicAbs);
  const randomSigma = Number(uncertainty.randomSigma);
  const confidenceK = Number(uncertainty.confidenceK);
  const k = Number.isFinite(confidenceK) ? Math.abs(confidenceK) : 2;
  const delta =
    (Number.isFinite(systematic) ? Math.abs(systematic) : 0) +
    (Number.isFinite(randomSigma) ? Math.abs(randomSigma) * k : 0);
  return Number.isFinite(delta) ? delta : 0;
}

/**
 * Format the displayed value based on decimal configuration.
 */
function formatValue(val, decimals) {
  if (val === null || val === undefined) return "---";
  const decs = decimals === undefined || decimals === null ? 2 : decimals;
  if (decs === -1) {
    // "Auto": cut off all trailing zeroes.
    const str = val.toFixed(10);
    return String(parseFloat(str));
  }
  return val.toFixed(decs);
}

// ==========================================
// METRIC SETTINGS MENU (FLOATING DROPDOWN)
// ==========================================
const SettingsMenu = ({ task, onClose, onUpdateTask }) => {
  const sourceTask = task.inputs?.source || task;
  const configFields = sourceTask.config?.configFields || [];
  const providerId = sourceTask.originalId || sourceTask.id;

  const [localValues, setLocalValues] = useState(() => {
    const initial = {};
    configFields.forEach((field) => {
      initial[field.key] = sourceTask.config?.[field.key] ?? field.value ?? field.default ?? "";
    });
    return initial;
  });

  const handleChange = (key, val) => {
    const nextValues = { ...localValues, [key]: val };
    setLocalValues(nextValues);
    
    // Update local task state
    let newTask;
    if (task.inputs?.source) {
      newTask = {
        ...task,
        inputs: {
          ...task.inputs,
          source: {
            ...task.inputs.source,
            config: { ...task.inputs.source.config, ...nextValues }
          }
        }
      };
    } else {
      newTask = {
        ...task,
        config: { ...task.config, ...nextValues }
      };
    }
    onUpdateTask(newTask);

    // Send control command to hardware
    if (providerId) {
      dispatcher.sendControlCommand(`prov_${providerId}`, {
        action: "update_config",
        payload: { [key]: val },
      });
    }
  };

  const menuRef = useRef(null);
  useEffect(() => {
    const handleClickOutside = (e) => {
      if (menuRef.current && !menuRef.current.contains(e.target)) {
        onClose();
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [onClose]);

  return (
    <div
      ref={menuRef}
      className="absolute top-10 right-2 z-50 bg-slate-950/95 backdrop-blur border border-slate-700/80 rounded-lg shadow-2xl p-3 min-w-[200px] text-left space-y-3"
    >
      <div className="flex items-center justify-between border-b border-slate-800 pb-1.5 mb-1.5 shrink-0">
        <span className="text-[10px] font-bold text-slate-400 uppercase tracking-widest flex items-center gap-1.5">
          <Icons.Settings size={11} /> Settings
        </span>
        <button
          onClick={onClose}
          className="p-0.5 text-slate-500 hover:text-slate-300 rounded hover:bg-slate-800 transition-colors"
        >
          <Icons.X size={12} />
        </button>
      </div>
      
      {configFields.map((field) => (
        <div key={field.key} className="space-y-1">
          <label className="text-[10px] font-bold text-slate-400 uppercase tracking-wider block">
            {field.label}
          </label>
          {field.type === "select" && (
            <select
              value={localValues[field.key]}
              onChange={(e) => {
                const opt = field.options?.find(o => String(o.value) === e.target.value);
                const val = opt ? opt.value : e.target.value;
                handleChange(field.key, val);
              }}
              className="w-full bg-slate-900 text-slate-200 text-[11px] p-1.5 rounded border border-slate-700 focus:border-blue-500 outline-none cursor-pointer"
            >
              {(field.options || []).map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          )}
          {field.type === "toggle" && (
            <label className="relative inline-flex items-center cursor-pointer pt-0.5">
              <input
                type="checkbox"
                className="sr-only peer"
                checked={!!localValues[field.key]}
                onChange={(e) => handleChange(field.key, e.target.checked)}
              />
              <div className="w-7 h-4 bg-slate-700 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-slate-300 after:border after:rounded-full after:h-3 after:w-3 after:transition-all peer-checked:bg-blue-500"></div>
              <span className="ml-2 text-[10px] font-medium text-slate-400">{localValues[field.key] ? 'On' : 'Off'}</span>
            </label>
          )}
        </div>
      ))}
    </div>
  );
};

// ==========================================
// METRIC WIDGET
// ==========================================
const getAcDcIndicator = (ch) => {
  if (ch.config?.ac_dc) {
    return ch.config.ac_dc;
  }
  const id = (ch.id || "").toLowerCase();
  const name = (ch.name || "").toLowerCase();
  if (id.includes("ac") || name.includes("ac") || name.includes("(ac)")) {
    return "AC";
  }
  if (id.includes("dc") || name.includes("dc") || name.includes("(dc)")) {
    return "DC";
  }
  return null;
};

export const MetricWidget = ({
  task,
  isConfigMode,
  streamBuffers,
  onUpdateTask,
  isPaused = false,
  showUncertainty = false,
}) => {
  const [readings, setReadings] = useState({});
  const [menuOpen, setMenuOpen] = useState(false);
  const requestRef = useRef(null);

  // Collect all displayable channels:
  //   - task.inputs.source (Measure-style: linked sensor as primary)
  //   - task itself (Generator/Sensor-style: task IS the data source)
  //   - task.extraChannels (additional channels)
  // Deduplicate by id so a task doesn't appear twice.
  const allChannels = useMemo(() => {
    const channels = [];
    const seen = new Set();

    // Primary linked source (Measure pattern)
    if (task.inputs?.source) {
      channels.push(task.inputs.source);
      seen.add(task.inputs.source.id);
    }

    // The task itself as a data source (Sensor/Generator pattern),
    // but only when there is no linked source or singleSource is set.
    if (!task.inputs?.source || task.config?.singleSource) {
      if (!seen.has(task.id)) {
        channels.push(task);
        seen.add(task.id);
      }
    }

    // Extra channels
    for (const ch of task.extraChannels || []) {
      if (!seen.has(ch.id)) {
        channels.push(ch);
        seen.add(ch.id);
      }
    }

    return channels;
  }, [task]);

  // Refs mirror the latest values for the rAF loop below, which must not be
  // restarted on every channel/pause change.
  const allChannelsRef = useRef(allChannels);
  const isPausedRef = useRef(isPaused);
  useEffect(() => {
    allChannelsRef.current = allChannels;
    isPausedRef.current = isPaused;
  }, [allChannels, isPaused]);

  // Sample the stream buffers on the browser render cycle. While paused the
  // last sampled readings stay in state, freezing the display.
  useEffect(() => {
    let lastTime = performance.now();

    const update = (time) => {
      if (time - lastTime >= 100) {
        if (!isPausedRef.current) {
          const next = {};
          allChannelsRef.current.forEach((ch) => {
            const buffer = streamBuffers?.get(ch.id) || streamBuffers?.get(ch.originalId);
            const point = buffer?.last?.();
            next[ch.id] = {
              value: getLatestValue(streamBuffers, ch.id, ch.originalId),
              uncertainty: point?.u || buffer?.getLatestUncertainty?.() || null,
            };
          });
          setReadings(next);
        }
        lastTime = time;
      }
      requestRef.current = requestAnimationFrame(update);
    };

    requestRef.current = requestAnimationFrame(update);
    return () => cancelAnimationFrame(requestRef.current);
  }, [streamBuffers]);

  // Per-channel range mode stored in task.config.rangeModes = { [channelId]: "auto"|"m"|"k"|... }
  const rangeModes = useMemo(() => task.config?.rangeModes || {}, [task.config?.rangeModes]);

  const getChannelRange = useCallback(
    (chId) => rangeModes[chId] ?? task.config?.rangeMode ?? "auto",
    [rangeModes, task.config?.rangeMode],
  );

  const setChannelRange = useCallback(
    (chId, mode) => {
      onUpdateTask({
        ...task,
        config: {
          ...task.config,
          rangeModes: { ...rangeModes, [chId]: mode },
        },
      });
    },
    [task, onUpdateTask, rangeModes],
  );

  const handleRangeToggle = useCallback(
    (chId) => {
      const cycle = ["auto", "", "k", "M", "m", "µ"];
      const current = getChannelRange(chId);
      const idx = cycle.indexOf(current);
      const next = cycle[(idx + 1) % cycle.length];
      setChannelRange(chId, next);
    },
    [getChannelRange, setChannelRange],
  );

  const handleDecimalsToggle = useCallback(
    (chId, currentDecimals) => {
      const cycle = [null, -1, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10];
      const current = currentDecimals === undefined || currentDecimals === null ? null : currentDecimals;
      const idx = cycle.indexOf(current);
      const next = cycle[(idx + 1) % cycle.length];
      
      let newTask;
      if (task.id === chId) {
        newTask = { ...task, decimals: next };
      } else if (task.inputs?.source?.id === chId) {
        newTask = {
          ...task,
          inputs: {
            ...task.inputs,
            source: { ...task.inputs.source, decimals: next }
          }
        };
      } else {
        newTask = {
          ...task,
          extraChannels: (task.extraChannels || []).map(ch => 
            ch.id === chId ? { ...ch, decimals: next } : ch
          )
        };
      }
      onUpdateTask(newTask);

      dispatcher.socket?.emit("set_task_decimals", {
        task_id: chId,
        decimals: next
      });
    },
    [task, onUpdateTask]
  );

  // Config mode.
  if (isConfigMode) {
    return (
      <div className="p-4 space-y-4">
        <ColorPicker task={task} onUpdateTask={onUpdateTask} />
        {allChannels.map((ch) => {
          const chRange = getChannelRange(ch.id);
          return (
            <div key={ch.id} className="border-t border-slate-700 pt-3">
              <label className="text-xs text-slate-400 uppercase tracking-wider block mb-2">
                Range — <span style={{ color: ch.color }}>{ch.name}</span>
              </label>
              <div className="flex flex-wrap gap-2">
                {["auto", "", "m", "µ", "k", "M", "G"].map((mode) => (
                  <button
                    key={mode}
                    onClick={() => setChannelRange(ch.id, mode)}
                    className={`px-3 py-1 rounded text-xs font-mono ${
                      chRange === mode
                        ? "bg-blue-600 text-white"
                        : "bg-slate-700 text-slate-300 hover:bg-slate-600"
                    }`}
                  >
                    {mode === "auto" ? "Auto" : mode === "" ? "1x" : mode}
                  </button>
                ))}
              </div>
            </div>
          );
        })}
      </div>
    );
  }

  // Render.
  const configFields = task.config?.configFields || [];

  return (
    <div className="h-full w-full flex flex-col items-center justify-center p-4 overflow-y-auto custom-scrollbar bg-slate-900 relative">
      {configFields.length > 0 && (
        <div className="absolute top-2 right-2 z-10">
          <button
            onClick={() => setMenuOpen((prev) => !prev)}
            className="p-1.5 text-slate-400 bg-slate-950/40 hover:bg-slate-800 hover:text-white rounded-full border border-slate-800/80 transition-all shadow-md"
            title="DMM Settings"
          >
            <Icons.Settings size={14} />
          </button>
          {menuOpen && (
            <SettingsMenu
              task={task}
              onClose={() => setMenuOpen(false)}
              onUpdateTask={onUpdateTask}
            />
          )}
        </div>
      )}
      {allChannels.map((ch) => {
        const reading = readings[ch.id];
        const rawValue = reading?.value ?? null;
        const config = getConfig(task, ch);
        const baseValue = rawValue !== null ? rawValue * config.factor : null;
        const baseDelta = showUncertainty ? uncertaintyDelta(reading?.uncertainty) * config.factor : 0;
        const rangeMode = getChannelRange(ch.id);

        let displayValue, displayUnit, scaleExp = 0, scaledValue = null;
        const decimals = ch.decimals;
        if (baseValue === null) {
          displayValue = "---";
          displayUnit = config.unit;
        } else if (rangeMode === "auto") {
          const { scaled, prefix, exp } = autoRange(baseValue);
          displayValue = formatValue(scaled, decimals);
          displayUnit = prefix + config.unit;
          scaleExp = exp;
          scaledValue = scaled;
        } else {
          const entry = SI_PREFIXES.find((p) => p.symbol === rangeMode);
          if (entry) {
            const { scaled, prefix, exp } = fixedRange(baseValue, entry);
            displayValue = formatValue(scaled, decimals);
            displayUnit = prefix + config.unit;
            scaleExp = exp;
            scaledValue = scaled;
          } else {
            displayValue = formatValue(baseValue, decimals);
            displayUnit = config.unit;
            scaledValue = baseValue;
          }
        }

        const scaledDelta = baseDelta > 0 ? baseDelta / Math.pow(10, scaleExp) : 0;
        const intervalText = scaledDelta > 0 && scaledValue !== null
          ? `${scaledValue.toFixed(3)} [+${(scaledValue + scaledDelta).toFixed(3)} -${(scaledValue - scaledDelta).toFixed(3)}]`
          : null;
        const acDc = getAcDcIndicator(ch);

        return (
          <div key={ch.id} className="text-center mb-4 last:mb-0">
            {(acDc || ch.config?.simulated) && (
              <div className="flex justify-center items-center gap-1.5 mb-1">
                {acDc && (
                  <span className="px-2 py-0.5 rounded-full text-[9px] font-extrabold tracking-widest bg-slate-850 text-slate-400 border border-slate-700/60 shadow-sm">
                    {acDc}
                  </span>
                )}
                {ch.config?.simulated && (
                  <span className="px-2 py-0.5 rounded-full text-[9px] font-extrabold tracking-widest bg-amber-950/60 text-amber-500 border border-amber-800/60 shadow-sm uppercase">
                    Simulated
                  </span>
                )}
              </div>
            )}
            <div
              className="text-5xl font-mono font-bold tracking-tighter drop-shadow-lg"
              style={{ color: ch.color }}
            >
              {displayValue}
              <span className="text-2xl text-slate-600 ml-1">
                {displayUnit}
              </span>
            </div>
            {scaledDelta > 0 && (
              <>
                <div className="mt-1 text-[11px] text-slate-400 font-mono">
                  ±{scaledDelta.toFixed(3)} {displayUnit}
                </div>
                {intervalText && (
                  <div className="mt-0.5 text-[10px] text-slate-500 font-mono">
                    {intervalText} {displayUnit}
                  </div>
                )}
              </>
            )}
            <div className="text-[10px] text-slate-500 uppercase tracking-widest mt-1 flex items-center justify-center gap-2">
              <span>{ch.name}</span>
              <button
                onClick={() => handleRangeToggle(ch.id)}
                className="text-[9px] px-1.5 py-0.5 rounded bg-slate-800 text-slate-400 hover:bg-slate-700 hover:text-slate-200 transition-colors"
                title="Toggle range mode"
              >
                {rangeMode === "auto" ? "AUTO" : rangeMode === "" ? "1x" : rangeMode}
              </button>
              <button
                onClick={() => handleDecimalsToggle(ch.id, ch.decimals)}
                className="text-[9px] px-1.5 py-0.5 rounded bg-slate-800 text-slate-400 hover:bg-slate-700 hover:text-slate-200 transition-colors ml-1.5"
                title="Toggle decimal places"
              >
                {ch.decimals === undefined || ch.decimals === null ? "DEC: 2" : ch.decimals === -1 ? "DEC: AUTO" : `DEC: ${ch.decimals}`}
              </button>
            </div>
          </div>
        );
      })}
    </div>
  );
};

export const MetricPlugin = {
  id: "tpl_metric",
  name: "Metric Display",
  type: "UI_TEMPLATE",
  render: MetricWidget,
};
