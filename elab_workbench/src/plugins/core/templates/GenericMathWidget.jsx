/* eslint-disable react-refresh/only-export-components */
import React, { useState, useCallback } from "react";
import { Icons } from "../../../utils/Shared";
import dispatcher from "../../../services/DispatcherClient";

// ==========================================
// GENERIC MATH PLUGIN TEMPLATE
// Provides a drop zone for input signals (sink) and renders
// configFields from the manifest dynamically.
// Suitable for any MATH-type task registered via the Python API
// or built-in plugins that follow the configFields convention.
// ==========================================

const toSourceRef = (taskRef) => {
  if (!taskRef) return null;
  return {
    id: taskRef.id,
    originalId: taskRef.originalId || taskRef.id,
    name: taskRef.name,
    color: taskRef.color,
    config: taskRef.config || {},
    providerId: taskRef.providerId,
  };
};

const GenericMathWidget = ({ task, isConfigMode, onUpdateTask }) => {
  const configFields = task.config?.configFields || [];
  const source = task.inputs?.source || null;
  const providerId = task.originalId || task.id;

  const [values, setValues] = useState(() => {
    const initial = {};
    configFields.forEach((field) => {
      initial[field.key] = task.config?.[field.key] ?? field.value ?? field.default ?? "";
    });
    return initial;
  });

  const handleChange = useCallback(
    (key, value) => {
      setValues((prev) => ({ ...prev, [key]: value }));

      // Immediately apply to local task state
      const newConfig = { ...task.config, [key]: value };
      onUpdateTask({ ...task, config: newConfig });

      // Send config update to provider
      dispatcher.sendControlCommand(`prov_${providerId}`, {
        action: "update_config",
        payload: { [key]: value },
      });
    },
    [task, onUpdateTask, providerId],
  );

  const sendInputUpdate = useCallback(
    (nextSource) => {
      dispatcher.sendControlCommand(`prov_${providerId}`, {
        action: "update_input",
        payload: { source: toSourceRef(nextSource) },
      });
    },
    [providerId],
  );

  const handleDrop = (e) => {
    e.preventDefault();
    e.stopPropagation();
    try {
      const droppedTask = JSON.parse(e.dataTransfer.getData("task"));
      if (!droppedTask || droppedTask.id === task.id) return;

      const nextSource = toSourceRef(droppedTask);
      const nextUnit = nextSource?.config?.unit || task.config?.unit || "";

      onUpdateTask({
        ...task,
        inputs: { source: nextSource },
        config: { ...task.config, unit: nextUnit },
      });
      sendInputUpdate(nextSource);
    } catch (error) {
      console.error("Error handling source drop in GenericMathWidget:", error);
    }
  };

  const handleDragOver = (e) => {
    e.preventDefault();
    e.stopPropagation();
  };

  const clearSource = () => {
    onUpdateTask({ ...task, inputs: { source: null } });
    sendInputUpdate(null);
  };

  // --- Drop Zone ---
  const dropZone = (
    <div
      onDragOver={handleDragOver}
      onDrop={handleDrop}
      className="bg-slate-950 p-3 rounded-lg border border-slate-800"
    >
      <div className="text-xs text-slate-400 mb-2">Eingangskanal</div>
      {source ? (
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2 min-w-0">
            <span
              className="w-2.5 h-2.5 rounded-full shrink-0"
              style={{ backgroundColor: source.color || "#64748b" }}
            />
            <span className="text-xs text-slate-200 truncate">
              {source.name || source.id}
            </span>
          </div>
          <button
            onClick={clearSource}
            className="text-slate-500 hover:text-red-400 hover:bg-red-900/20 p-1 rounded transition-colors"
            title="Eingang entfernen"
          >
            <Icons.Trash2 size={14} />
          </button>
        </div>
      ) : (
        <div className="text-[11px] text-slate-500 italic">
          Sensor oder Generator hier hineinziehen
        </div>
      )}
    </div>
  );

  // --- Dynamic Config Fields ---
  const configContent = configFields.length > 0 && (
    <div className="space-y-3">
      {configFields.map((field) => (
        <div
          key={field.key}
          className="bg-slate-950 p-3 rounded-lg border border-slate-800"
        >
          <div className="flex justify-between items-center mb-2">
            <label className="text-xs text-slate-400">{field.label}</label>
            {(field.type === "number" || field.type === "slider") && (
              <span className="text-xs text-slate-500 font-mono">
                {values[field.key]} {field.unit || ""}
              </span>
            )}
          </div>

          {(field.type === "number" || field.type === "slider") && (
            <>
              <input
                type={field.type === "slider" ? "range" : "number"}
                min={field.min}
                max={field.max}
                step={field.step || 1}
                value={values[field.key]}
                onChange={(e) => handleChange(field.key, Number(e.target.value))}
                className={
                  field.type === "slider"
                    ? "w-full accent-cyan-500"
                    : "w-full bg-slate-900 text-slate-200 text-xs p-2 rounded border border-slate-700 focus:border-cyan-500 outline-none"
                }
              />
              {field.type === "slider" && (
                <div className="flex justify-between text-[10px] text-slate-600 mt-1">
                  <span>{field.min} {field.unit || ""}</span>
                  <span>{field.max} {field.unit || ""}</span>
                </div>
              )}
            </>
          )}

          {field.type === "select" && (
            <select
              value={values[field.key]}
              onChange={(e) =>
                handleChange(
                  field.key,
                  field.options?.find((o) => String(o.value) === e.target.value)
                    ?.value ?? e.target.value,
                )
              }
              className="w-full bg-slate-900 text-slate-200 text-xs p-2 rounded border border-slate-700 focus:border-cyan-500 outline-none"
            >
              {(field.options || []).map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          )}

          {field.type === "toggle" && (
            <label className="relative inline-flex items-center cursor-pointer">
              <input
                type="checkbox"
                className="sr-only peer"
                checked={!!values[field.key]}
                onChange={(e) => handleChange(field.key, e.target.checked)}
              />
              <div className="w-9 h-5 bg-slate-700 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-slate-300 after:border after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:bg-cyan-500"></div>
              <span className="ml-3 text-xs text-slate-400">
                {values[field.key] ? "On" : "Off"}
              </span>
            </label>
          )}

          {field.type === "text" && (
            <input
              type="text"
              value={values[field.key]}
              onChange={(e) => handleChange(field.key, e.target.value)}
              placeholder={field.placeholder || ""}
              className="w-full bg-slate-900 text-slate-200 text-xs p-2 rounded border border-slate-700 focus:border-cyan-500 outline-none"
            />
          )}
        </div>
      ))}
    </div>
  );

  // --- Config Mode (WidgetMenu) ---
  if (isConfigMode) {
    return (
      <div className="p-4 bg-slate-900 h-full overflow-y-auto custom-scrollbar">
        {dropZone}
        {configContent && <div className="mt-3">{configContent}</div>}
      </div>
    );
  }

  // --- Normal View ---
  return (
    <div className="h-full flex flex-col bg-slate-900 text-slate-200 relative">
      <div
        onDragOver={handleDragOver}
        onDrop={handleDrop}
        className="h-full p-4 overflow-y-auto custom-scrollbar"
      >
        {dropZone}
        {configContent && <div className="mt-3">{configContent}</div>}

        {!source && (
          <div className="mt-3 text-center text-slate-500 p-3 border-2 border-dashed border-slate-700 rounded bg-slate-950/30">
            <Icons.Inbox className="mx-auto mb-2 opacity-50" size={24} />
            <p className="text-[10px] text-slate-600">
              Sensor oder Generator als Eingang zuweisen
            </p>
          </div>
        )}
      </div>
    </div>
  );
};

export const GenericMathPlugin = {
  id: "tpl_generic_math",
  name: "Generic Math",
  type: "UI_TEMPLATE",
  render: GenericMathWidget,
};
