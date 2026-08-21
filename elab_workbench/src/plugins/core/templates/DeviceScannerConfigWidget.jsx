/* eslint-disable react-refresh/only-export-components */
import React, { useState, useCallback } from "react";
import { Icons } from "../../../utils/Shared";
import dispatcher from "../../../services/DispatcherClient";

// ==========================================
// GENERIC DEVICE SCANNER CONFIG (tpl_device_scanner_config)
// Provides continuous device scanning, live preview of found devices,
// and persistent target device selection.
// ==========================================

const DeviceScannerConfigWidget = ({ task, onUpdateTask }) => {
  const [localScanning, setLocalScanning] = useState(!!task.config?.isScanning);
  const isScanning = !!task.config?.isScanning || localScanning;

  const providerId = (task.providerId || task.config?.providerId || task.originalId || task.id || "").replace(/^prov_/, "");
  const targetAddress = task.config?.targetAddress || null;
  const targetName = task.config?.targetName || "Kein Sensor gewählt";
  const discoveredDevices = task.config?.discoveredDevices || [];

  const handleToggleScan = useCallback(() => {
    if (!providerId) return;
    const nextScanning = !isScanning;
    setLocalScanning(nextScanning);

    // Update local task state
    if (onUpdateTask) {
      onUpdateTask({
        ...task,
        config: {
          ...task.config,
          isScanning: nextScanning,
          ...(nextScanning ? { discoveredDevices: [] } : {}),
        },
      });
    }

    // Command backend hardware scanner
    dispatcher.sendControlCommand(`prov_${providerId}`, {
      action: nextScanning ? "start_scan" : "stop_scan",
      payload: { timestamp: Date.now() },
    });
  }, [isScanning, providerId, task, onUpdateTask]);

  const handleSelectDevice = useCallback(
    (device) => {
      if (!providerId) return;
      setLocalScanning(false);

      // Apply selection to task
      if (onUpdateTask) {
        onUpdateTask({
          ...task,
          config: {
            ...task.config,
            targetAddress: device.address,
            targetName: device.name,
            isScanning: false,
          },
        });
      }

      // Send selected address to provider for persistent storage & connection
      dispatcher.sendControlCommand(`prov_${providerId}`, {
        action: "select_device",
        payload: {
          address: device.address,
          name: device.name,
          timestamp: Date.now(),
        },
      });
    },
    [providerId, task, onUpdateTask],
  );

  const handleDisconnect = useCallback(() => {
    if (!providerId) return;
    if (onUpdateTask) {
      onUpdateTask({
        ...task,
        config: {
          ...task.config,
          targetAddress: null,
          targetName: null,
        },
      });
    }
    dispatcher.sendControlCommand(`prov_${providerId}`, {
      action: "select_device",
      payload: { address: null, name: null, timestamp: Date.now() },
    });
  }, [providerId, task, onUpdateTask]);

  return (
    <div className="h-full w-full flex flex-col p-4 bg-slate-900 text-slate-200 overflow-y-auto custom-scrollbar select-none">
      {/* Header & Current Target Status */}
      <div className="flex items-center justify-between pb-3 border-b border-slate-800 mb-4 shrink-0">
        <div className="flex items-center gap-2">
          <Icons.Radio size={18} className="text-blue-400 animate-pulse" />
          <div>
            <div className="text-xs font-bold uppercase tracking-wider text-slate-300">
              Sensor Verbindung
            </div>
            <div className="text-[10px] text-slate-500 font-mono">
              Persistente Hardware Kopplung
            </div>
          </div>
        </div>

        <button
          onClick={handleToggleScan}
          className={`px-4 py-2 rounded-lg text-xs font-bold shadow-md transition-all flex items-center gap-2 ${
            isScanning
              ? "bg-red-600 hover:bg-red-500 text-white animate-pulse"
              : "bg-blue-600 hover:bg-blue-500 text-white"
          }`}
        >
          {isScanning ? (
            <>
              <Icons.Loader size={14} className="animate-spin" /> Scan stoppen
            </>
          ) : (
            <>
              <Icons.Search size={14} /> Nach Geräten scannen
            </>
          )}
        </button>
      </div>

      {/* Currently Linked Device Badge */}
      <div className="bg-slate-950 p-3.5 rounded-xl border border-slate-800 shadow-inner mb-4 shrink-0">
        <div className="text-[10px] uppercase tracking-wider text-slate-400 font-bold mb-1 flex items-center justify-between">
          <span>Aktuelles Gerät</span>
          {targetAddress ? (
            <span className="text-emerald-400 flex items-center gap-1">
              <span className="w-2 h-2 rounded-full bg-emerald-500 inline-block animate-ping" />
              Verbunden & Gespeichert
            </span>
          ) : (
            <span className="text-amber-500 font-normal">Kein Ziel ausgewählt (Alle Daten werden ignoriert oder gescannt)</span>
          )}
        </div>
        <div className="flex items-center justify-between mt-2">
          <div>
            <div className="text-sm font-extrabold text-white font-mono">
              {targetName || "Unbekannter Sensor"}
            </div>
            {targetAddress && (
              <div className="text-xs text-slate-400 font-mono mt-0.5">
                MAC: <span className="text-blue-400 font-extrabold">{targetAddress}</span>
              </div>
            )}
          </div>
          {targetAddress && (
            <button
              onClick={handleDisconnect}
              className="text-xs text-slate-400 hover:text-red-400 bg-slate-900 hover:bg-slate-800 px-3 py-1.5 rounded-lg border border-slate-700/60 transition-colors font-mono"
              title="Kopplung aufheben"
            >
              Trennen
            </button>
          )}
        </div>
      </div>

      {/* Discovered Devices List */}
      <div className="flex-1 flex flex-col min-h-0">
        <div className="text-xs font-bold text-slate-400 uppercase tracking-wider mb-2 flex items-center justify-between shrink-0">
          <span>Gefundene Geräte ({discoveredDevices.length})</span>
          {isScanning && <span className="text-[10px] text-blue-400 font-mono">Suche läuft kontinuierlich...</span>}
        </div>

        <div className="space-y-2.5 flex-1 overflow-y-auto custom-scrollbar pr-1">
          {discoveredDevices.length === 0 ? (
            <div className="h-40 flex flex-col items-center justify-center border-2 border-dashed border-slate-800 rounded-xl text-slate-600 text-center p-6">
              <Icons.Wifi size={28} className="mb-2 opacity-30" />
              <p className="text-xs font-medium text-slate-500">
                {isScanning ? "Suche nach Sensoren im Bereich..." : "Keine Geräte gelistet."}
              </p>
              {!isScanning && (
                <p className="text-[10px] text-slate-600 mt-1">
                  Klicke auf &quot;Nach Geräten scannen&quot;, um Sensoren im Netzwerk oder über Bluetooth (BLE) zu finden.
                </p>
              )}
            </div>
          ) : (
            discoveredDevices.map((dev) => {
              const isSelected = targetAddress && dev.address && dev.address.toUpperCase() === targetAddress.toUpperCase();
              return (
                <div
                  key={dev.address}
                  onClick={() => handleSelectDevice(dev)}
                  className={`p-3.5 rounded-xl border transition-all cursor-pointer group flex items-center justify-between ${
                    isSelected
                      ? "bg-blue-950/40 border-blue-500/80 shadow-[0_0_12px_rgba(59,130,246,0.2)]"
                      : "bg-slate-950/90 border-slate-800/80 hover:border-slate-700 hover:bg-slate-900/60"
                  }`}
                >
                  <div className="flex-1 min-w-0 pr-3">
                    <div className="flex items-center gap-2 mb-1">
                      <span className="font-extrabold font-mono text-sm text-slate-200 group-hover:text-white truncate">
                        {dev.name || "Govee Sensor"}
                      </span>
                      {isSelected && (
                        <span className="px-2 py-0.5 rounded-full bg-blue-500/20 text-blue-300 text-[10px] font-bold uppercase tracking-wider">
                          Aktiv
                        </span>
                      )}
                    </div>
                    <div className="text-[11px] font-mono text-slate-400 flex items-center gap-3">
                      <span>Adresse: <strong className="text-slate-300">{dev.address}</strong></span>
                      {dev.rssi && (
                        <span className="flex items-center gap-1 text-slate-400">
                          <Icons.Signal size={12} className="text-slate-400" />
                          {dev.rssi} dBm
                        </span>
                      )}
                    </div>

                    {/* Sensor Data Preview if available during scan */}
                    {(dev.temp_c !== undefined || dev.humidity !== undefined) && (
                      <div className="flex items-center gap-4 mt-2 pt-2 border-t border-slate-800/60 text-xs font-mono">
                        {dev.temp_c !== undefined && (
                          <span className="text-rose-400 font-bold flex items-center gap-1">
                            🌡️ {dev.temp_c.toFixed(2)} °C
                          </span>
                        )}
                        {dev.humidity !== undefined && (
                          <span className="text-cyan-400 font-bold flex items-center gap-1">
                            💧 {dev.humidity.toFixed(1)} %
                          </span>
                        )}
                        {dev.battery !== undefined && (
                          <span className="text-emerald-400 text-[11px] font-bold">
                            🔋 {dev.battery}%
                          </span>
                        )}
                      </div>
                    )}
                  </div>

                  <div className="shrink-0">
                    <button
                      className={`px-3 py-1.5 rounded-lg text-xs font-bold font-mono transition-colors ${
                        isSelected
                          ? "bg-blue-600 text-white"
                          : "bg-slate-800 text-slate-300 group-hover:bg-blue-600 group-hover:text-white"
                      }`}
                    >
                      {isSelected ? "Ausgewählt" : "Auswählen"}
                    </button>
                  </div>
                </div>
              );
            })
          )}
        </div>
      </div>
    </div>
  );
};

export const DeviceScannerConfigPlugin = {
  id: "tpl_device_scanner_config",
  name: "Device Scanner Config",
  type: "UI_TEMPLATE",
  render: DeviceScannerConfigWidget,
};
