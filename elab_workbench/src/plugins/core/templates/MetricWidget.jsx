/* eslint-disable react-refresh/only-export-components */
import React, {
    useState,
    useEffect,
    useRef,
    useMemo,
    useCallback,
} from "react";
import { ColorPicker } from "../../../utils/Shared";
import { getConfig, getLatestValue } from "../utils/configUtils";

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
 * Returns { scaled, prefix } where scaled is the value divided by 10^exp.
 */
function autoRange(value) {
  const abs = Math.abs(value);
  if (abs === 0) return { scaled: 0, prefix: "" };

  for (let i = SI_PREFIXES.length - 1; i >= 0; i--) {
    if (abs >= Math.pow(10, SI_PREFIXES[i].exp)) {
      return {
        scaled: value / Math.pow(10, SI_PREFIXES[i].exp),
        prefix: SI_PREFIXES[i].symbol,
      };
    }
  }
  // Smaller than pico — use the smallest
  return {
    scaled: value / Math.pow(10, SI_PREFIXES[0].exp),
    prefix: SI_PREFIXES[0].symbol,
  };
}

/**
 * Apply a fixed SI prefix to the value.
 */
function fixedRange(value, prefixEntry) {
  return {
    scaled: value / Math.pow(10, prefixEntry.exp),
    prefix: prefixEntry.symbol,
  };
}

// ==========================================
// METRIC WIDGET
// ==========================================
const MetricWidget = ({
  task,
  isConfigMode,
  streamBuffers,
  onUpdateTask,
}) => {
  const [, setTick] = useState(0);
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

  // Use requestAnimationFrame instead of setInterval.
  useEffect(() => {
    let lastTime = performance.now();

    const update = (time) => {
      if (time - lastTime >= 100) {
        setTick((t) => t + 1);
        lastTime = time;
      }
      requestRef.current = requestAnimationFrame(update);
    };

    requestRef.current = requestAnimationFrame(update);
    return () => cancelAnimationFrame(requestRef.current);
  }, []);

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
  return (
    <div className="h-full flex flex-col items-center justify-center p-4 overflow-y-auto custom-scrollbar bg-slate-900">
      {allChannels.map((ch) => {
        const rawValue = getLatestValue(streamBuffers, ch.id, ch.originalId);
        const config = getConfig(task, ch);
        const baseValue = rawValue !== null ? rawValue * config.factor : null;
        const rangeMode = getChannelRange(ch.id);

        let displayValue, displayUnit;
        if (baseValue === null) {
          displayValue = "---";
          displayUnit = config.unit;
        } else if (rangeMode === "auto") {
          const { scaled, prefix } = autoRange(baseValue);
          displayValue = scaled.toFixed(2);
          displayUnit = prefix + config.unit;
        } else {
          const entry = SI_PREFIXES.find((p) => p.symbol === rangeMode);
          if (entry) {
            const { scaled, prefix } = fixedRange(baseValue, entry);
            displayValue = scaled.toFixed(2);
            displayUnit = prefix + config.unit;
          } else {
            displayValue = baseValue.toFixed(2);
            displayUnit = config.unit;
          }
        }

        return (
          <div key={ch.id} className="text-center mb-4 last:mb-0">
            <div
              className="text-5xl font-mono font-bold tracking-tighter drop-shadow-lg"
              style={{ color: ch.color }}
            >
              {displayValue}
              <span className="text-2xl text-slate-600 ml-1">
                {displayUnit}
              </span>
            </div>
            <div className="text-[10px] text-slate-500 uppercase tracking-widest mt-1 flex items-center justify-center gap-2">
              <span>{ch.name}</span>
              <button
                onClick={() => handleRangeToggle(ch.id)}
                className="text-[9px] px-1.5 py-0.5 rounded bg-slate-800 text-slate-400 hover:bg-slate-700 hover:text-slate-200 transition-colors"
                title="Toggle range mode"
              >
                {rangeMode === "auto" ? "AUTO" : rangeMode === "" ? "1x" : rangeMode}
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
