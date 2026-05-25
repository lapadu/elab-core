/* eslint-disable react-refresh/only-export-components */
import React, { useState, useCallback } from "react";
import { Icons } from "../../../utils/Shared";
import dispatcher from "../../../services/DispatcherClient";

// ==========================================
// GENERIC DEVICE CONFIG TEMPLATE
// Reads configurable parameters from task.config.configFields
// and sends changes through update_config to the hardware provider.
// ==========================================
const DeviceConfigWidget = ({ task, onUpdateTask }) => {
  const configFields = task.config?.configFields || [];
  const providerId = task.providerId || task.config?.providerId || task.originalId || task.id;

  // Local state for editable values.
  const [values, setValues] = useState(() => {
    const initial = {};
    configFields.forEach((field) => {
      initial[field.key] = task.config?.[field.key] ?? field.value ?? field.default ?? "";
    });
    return initial;
  });

  const handleChange = useCallback((key, value) => {
    setValues((prev) => ({ ...prev, [key]: value }));
  }, []);

  const handleApply = useCallback(() => {
    if (!providerId) return;

    // Update the local task first.
    const newConfig = { ...task.config, ...values };
    onUpdateTask({ ...task, config: newConfig });

    // Then send the command to the hardware provider.
    dispatcher.sendControlCommand(`prov_${providerId}`, {
      action: "update_config",
      payload: values,
    });
  }, [providerId, values, task, onUpdateTask]);

  const handleAction = useCallback((actionId) => {
    if (!providerId) return;
    dispatcher.sendControlCommand(`prov_${providerId}`, {
      action: actionId,
      payload: { timestamp: Date.now() },
    });
  }, [providerId]);

  if (configFields.length === 0) {
    return (
      <div className="h-full flex items-center justify-center text-slate-500 text-xs">
        No configurable parameters available.
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col p-4 bg-slate-900 overflow-y-auto custom-scrollbar">
      <div className="text-xs font-bold text-slate-500 uppercase mb-4 flex items-center gap-2">
        <Icons.Settings size={14} /> Device Configuration
      </div>

      <div className="space-y-4 flex-1">
        {configFields.map((field) => (
          <div
            key={field.key}
            className="bg-slate-950 p-3 rounded-lg border border-slate-800"
          >
            <div className="flex justify-between items-center mb-2">
              <label className="text-xs font-bold text-slate-300">
                {field.label}
              </label>
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
                  onChange={(e) =>
                    handleChange(field.key, Number(e.target.value))
                  }
                  className={field.type === "slider" 
                    ? "w-full h-2 bg-slate-800 rounded-lg appearance-none cursor-pointer accent-blue-500 mb-1" 
                    : "w-full bg-slate-900 text-slate-200 text-xs p-2 rounded border border-slate-700 focus:border-blue-500 outline-none"}
                />
                {field.type === "slider" && (
                  <div className="flex justify-between text-[10px] text-slate-600">
                    <span>
                      {field.min} {field.unit || ""}
                    </span>
                    <span>
                      {field.max} {field.unit || ""}
                    </span>
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
                    field.options?.find(
                      (o) => String(o.value) === e.target.value,
                    )?.value ?? e.target.value,
                  )
                }
                className="w-full bg-slate-900 text-slate-200 text-xs p-2 rounded border border-slate-700 focus:border-blue-500 outline-none"
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
                <div className="w-9 h-5 bg-slate-700 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-slate-300 after:border after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:bg-blue-500"></div>
                <span className="ml-3 text-xs font-medium text-slate-400">{values[field.key] ? 'On' : 'Off'}</span>
              </label>
            )}

            {field.type === "datetime" && (
              <input
                type="datetime-local"
                value={values[field.key]}
                onChange={(e) => handleChange(field.key, e.target.value)}
                className="w-full bg-slate-900 text-slate-200 text-xs p-2 rounded border border-slate-700 focus:border-blue-500 outline-none"
              />
            )}

            {field.type === "text" && (
              <input
                type="text"
                value={values[field.key]}
                onChange={(e) => handleChange(field.key, e.target.value)}
                placeholder={field.placeholder || ""}
                className="w-full bg-slate-900 text-slate-200 text-xs p-2 rounded border border-slate-700 focus:border-blue-500 outline-none"
              />
            )}

            {field.type === "button" && (
              <button
                onClick={() => handleAction(field.key)}
                className="w-full bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-bold py-2 px-4 rounded border border-slate-700 transition-colors"
              >
                {field.buttonText || field.label || "Action"}
              </button>
            )}
          </div>
        ))}
      </div>

      <button
        onClick={handleApply}
        className="mt-4 w-full bg-blue-600 hover:bg-blue-500 text-white text-xs font-bold py-2.5 px-4 rounded-lg transition-colors flex items-center justify-center gap-2 shrink-0"
      >
        <Icons.Send size={14} /> Konfiguration anwenden
      </button>
    </div>
  );
};

export const DeviceConfigPlugin = {
  id: "tpl_device_config",
  name: "Device Configuration",
  type: "UI_TEMPLATE",
  render: DeviceConfigWidget,
};
