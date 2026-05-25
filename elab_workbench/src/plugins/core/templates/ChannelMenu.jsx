import React, { useEffect, useRef, useState } from "react";
import { Icons, COLOR_PALETTE } from "../../../utils/Shared";

/**
 * Floating channel menu that appears when clicking the channel indicator.
 * Each channel is a compact single row: color dot (expands a palette),
 * name, special actions (e.g. RAW capture), and a remove button.
 */
const ChannelMenu = ({
  sources,
  onRemoveSource,
  onColorChange,
  onAction,
  rawCaptureAwaiting,
  singleSource,
  onClose,
  anchorRef,
}) => {
  const menuRef = useRef(null);
  const [expandedColorId, setExpandedColorId] = useState(null);

  // Close the menu when clicking outside.
  useEffect(() => {
    const handleClickOutside = (e) => {
      if (
        menuRef.current &&
        !menuRef.current.contains(e.target) &&
        (!anchorRef?.current || !anchorRef.current.contains(e.target))
      ) {
        onClose();
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [onClose, anchorRef]);

  return (
    <div
      ref={menuRef}
      className="absolute top-10 left-0 z-50 bg-slate-900/95 backdrop-blur border border-slate-700 rounded-lg shadow-2xl min-w-[180px] overflow-hidden"
    >
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-1.5 border-b border-slate-800 bg-slate-950/50">
        <span className="text-[10px] font-bold text-slate-400 uppercase tracking-widest flex items-center gap-1.5">
          <Icons.Layers size={11} />
          Channels ({sources.length})
        </span>
        <button
          onClick={onClose}
          className="p-0.5 text-slate-500 hover:text-slate-300 rounded hover:bg-slate-800 transition-colors"
        >
          <Icons.X size={12} />
        </button>
      </div>

      {/* Source list — one compact row per channel */}
      <div className="max-h-[300px] overflow-y-auto custom-scrollbar py-1">
        {sources.length === 0 && (
          <div className="px-3 py-3 text-center text-xs text-slate-600 italic">
            No channels connected.
          </div>
        )}

        {sources.map((s) => (
          <div key={s.id} className="px-3 py-1.5 hover:bg-slate-800/40 transition-colors">
            {/* Main row */}
            <div className="flex items-center gap-2">
              {/* Color dot — click toggles palette */}
              <button
                onClick={() => setExpandedColorId(prev => prev === s.id ? null : s.id)}
                className="w-4 h-4 rounded-full shrink-0 ring-1 ring-white/20 hover:ring-white/50 transition-all hover:scale-110"
                style={{ backgroundColor: s.color }}
                title="Change color"
              />

              {/* Name */}
              <span className="text-[11px] font-medium text-slate-300 truncate flex-1 min-w-0">
                {s.name}
              </span>

{/* Actions from manifest */}
            <div className="flex items-center gap-0.5 shrink-0">
              {(s.actions || []).map((action) => {
                const ActionIcon = Icons[action.icon] || Icons.Zap;
                const isRaw = action.id === 'START_RAW';
                return (
                  <button
                    key={action.id}
                    onClick={() => onAction(s, action.id)}
                    disabled={isRaw && rawCaptureAwaiting}
                    className={`p-1 rounded transition-colors ${
                      isRaw && rawCaptureAwaiting
                        ? "text-amber-400 animate-pulse"
                        : "text-slate-500 hover:text-amber-400 hover:bg-amber-900/20"
                    }`}
                    title={isRaw && rawCaptureAwaiting ? "Awaiting data..." : action.label}
                  >
                    <ActionIcon size={12} />
                  </button>
                );
              })}

                {!singleSource && (
                  <button
                    onClick={() => onRemoveSource(s.id)}
                    className="p-1 rounded text-slate-500 hover:text-red-400 hover:bg-red-900/20 transition-colors"
                    title="Remove channel"
                  >
                    <Icons.Trash2 size={12} />
                  </button>
                )}
              </div>
            </div>

            {/* Expandable color palette */}
            {expandedColorId === s.id && (
              <div className="flex gap-1 flex-wrap mt-1.5 ml-6">
                {COLOR_PALETTE.map((c) => (
                  <button
                    key={c}
                    onClick={() => { onColorChange(s.id, c); setExpandedColorId(null); }}
                    className={`w-4 h-4 rounded-full border-2 transition-transform hover:scale-125 ${
                      s.color === c
                        ? "border-white scale-110 shadow-md"
                        : "border-transparent"
                    }`}
                    style={{ backgroundColor: c }}
                  />
                ))}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
};

export default ChannelMenu;
