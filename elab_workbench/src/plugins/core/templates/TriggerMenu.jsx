import React, { useEffect, useRef } from "react";
import { Icons } from "../../../utils/Shared";

const TRIGGER_DRAG_TYPE = "application/x-elab-trigger";

const TriggerMenu = ({
  trigger,
  channels,
  onAssignChannel,
  onClose,
  anchorRef,
}) => {
  const menuRef = useRef(null);

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

  const onTriggerDragStart = (e) => {
    e.dataTransfer.setData(TRIGGER_DRAG_TYPE, "move-trigger");
    e.dataTransfer.effectAllowed = "move";
  };

  const handleDropOnChannel = (e, channelId) => {
    e.preventDefault();
    const payload = e.dataTransfer.getData(TRIGGER_DRAG_TYPE);
    if (!payload) return;
    onAssignChannel(channelId);
  };

  return (
    <div
      ref={menuRef}
      className="absolute top-10 left-24 z-50 bg-slate-900/95 backdrop-blur border border-slate-700 rounded-lg shadow-2xl min-w-[220px] overflow-hidden"
    >
      <div className="flex items-center justify-between px-3 py-1.5 border-b border-slate-800 bg-slate-950/50">
        <span className="text-[10px] font-bold text-slate-400 uppercase tracking-widest flex items-center gap-1.5">
          <Icons.Target size={11} /> Trigger
        </span>
        <button
          onClick={onClose}
          className="p-0.5 text-slate-500 hover:text-slate-300 rounded hover:bg-slate-800 transition-colors"
        >
          <Icons.X size={12} />
        </button>
      </div>

      <div className="max-h-[300px] overflow-y-auto custom-scrollbar py-1">
        {!trigger ? (
          <div className="px-3 py-3 text-center text-xs text-slate-600 italic">No trigger connected.</div>
        ) : (
          channels.map((ch, index) => {
            const isActive = trigger.channelId === ch.id;
            return (
              <div key={ch.id} className="px-3 py-1.5 hover:bg-slate-800/40 transition-colors">
                <div
                  onDragOver={(e) => e.preventDefault()}
                  onDrop={(e) => handleDropOnChannel(e, ch.id)}
                  className={`flex items-center gap-2 px-2 py-1 rounded border text-xs transition-colors ${
                    isActive
                      ? "bg-blue-600/20 border-blue-500 text-slate-100"
                      : "bg-slate-900 border-slate-700 text-slate-400 hover:border-slate-600"
                  }`}
                >
                  <div className="w-2 h-2 rounded-full" style={{ backgroundColor: ch.color }} />
                  <span className="truncate flex-1 min-w-0 text-[11px] font-semibold">CH{index + 1}</span>

                  {isActive ? (
                    <div
                      draggable
                      onDragStart={onTriggerDragStart}
                      className="flex items-center gap-1 px-1.5 py-0.5 rounded bg-slate-800 border border-slate-600 cursor-grab active:cursor-grabbing"
                      title="Drag trigger to another channel"
                    >
                      <Icons.Target size={10} className="text-yellow-500" />
                      <span className="text-[10px] lowercase">{trigger.mode || "trigger"}</span>
                      <span className="text-[10px] text-slate-500">lvl {Number(trigger.level || 0).toFixed(2)}</span>
                    </div>
                  ) : (
                    <span className="text-[10px] text-slate-600">drop target</span>
                  )}

                  {isActive && <Icons.Check size={11} className="text-blue-400" />}
                </div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
};

export default TriggerMenu;