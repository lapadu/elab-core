import React, { useEffect, useRef, useState } from "react";
import { Icons } from "../../../utils/Shared";

/**
 * Generic trigger menu.
 *
 * Lists every channel of the widget and the triggers assigned to it. Any
 * channel can hold one or more triggers; a single trigger is "active" and
 * drives the time-axis alignment in the scope. Triggers can be dragged between
 * channels using pointer events, which works for both mouse and touch (mobile)
 * input.
 */
const TriggerMenu = ({
  triggers = [],
  activeTriggerId,
  channels = [],
  onActivate,
  onMove,
  onRemove,
  onClose,
  anchorRef,
}) => {
  const menuRef = useRef(null);
  const dragRef = useRef(null); // { id, moved }
  const [dragState, setDragState] = useState(null); // { id, mode, x, y }

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

  // Pointer-based drag-to-move (works for mouse + touch).
  const dragging = dragState?.id ?? null;
  useEffect(() => {
    if (!dragging) return undefined;
    const onPointerMove = (ev) => {
      if (!dragRef.current) return;
      dragRef.current.moved = true;
      setDragState((s) => (s ? { ...s, x: ev.clientX, y: ev.clientY } : s));
    };
    const onPointerUp = (ev) => {
      const d = dragRef.current;
      dragRef.current = null;
      setDragState(null);
      if (!d) return;
      if (!d.moved) {
        onActivate?.(d.id);
        return;
      }
      const el = document.elementFromPoint(ev.clientX, ev.clientY);
      const target = el?.closest?.("[data-channel-id]");
      if (target) {
        const channelId = target.getAttribute("data-channel-id");
        onMove?.(d.id, channelId);
      }
    };
    window.addEventListener("pointermove", onPointerMove);
    window.addEventListener("pointerup", onPointerUp);
    window.addEventListener("pointercancel", onPointerUp);
    return () => {
      window.removeEventListener("pointermove", onPointerMove);
      window.removeEventListener("pointerup", onPointerUp);
      window.removeEventListener("pointercancel", onPointerUp);
    };
  }, [dragging, onMove, onActivate]);

  const beginDrag = (e, trigger) => {
    // Ignore secondary buttons for mouse input.
    if (e.button != null && e.button !== 0) return;
    dragRef.current = { id: trigger.id, moved: false };
    setDragState({ id: trigger.id, mode: trigger.mode, x: e.clientX, y: e.clientY });
  };

  return (
    <div
      ref={menuRef}
      className="absolute top-10 left-24 z-50 bg-slate-900/95 backdrop-blur border border-slate-700 rounded-lg shadow-2xl min-w-[240px] overflow-hidden"
    >
      <div className="flex items-center justify-between px-3 py-1.5 border-b border-slate-800 bg-slate-950/50">
        <span className="text-[10px] font-bold text-slate-400 uppercase tracking-widest flex items-center gap-1.5">
          <Icons.Target size={11} /> Triggers
        </span>
        <button
          onClick={onClose}
          className="p-0.5 text-slate-500 hover:text-slate-300 rounded hover:bg-slate-800 transition-colors"
        >
          <Icons.X size={12} />
        </button>
      </div>

      <div className="max-h-[320px] overflow-y-auto custom-scrollbar py-1">
        {channels.length === 0 ? (
          <div className="px-3 py-3 text-center text-xs text-slate-600 italic">No channels connected.</div>
        ) : (
          channels.map((ch, index) => {
            const chTriggers = triggers.filter((t) => t.channelId === ch.id);
            return (
              <div
                key={ch.id}
                data-channel-id={ch.id}
                className="px-3 py-1.5 hover:bg-slate-800/40 transition-colors"
              >
                <div className="flex items-center gap-2 mb-1">
                  <div className="w-2 h-2 rounded-full" style={{ backgroundColor: ch.color }} />
                  <span className="truncate flex-1 min-w-0 text-[11px] font-semibold text-slate-300">
                    CH{index + 1}
                  </span>
                </div>

                {chTriggers.length === 0 ? (
                  <div className="text-[10px] text-slate-600 italic pl-4">drop or add a trigger</div>
                ) : (
                  <div className="flex flex-wrap gap-1.5 pl-4">
                    {chTriggers.map((trg) => {
                      const isActive = trg.id === activeTriggerId;
                      return (
                        <div
                          key={trg.id}
                          onPointerDown={(e) => beginDrag(e, trg)}
                          style={{ touchAction: "none", userSelect: "none" }}
                          className={`flex items-center gap-1 px-1.5 py-0.5 rounded border cursor-grab active:cursor-grabbing transition-colors ${
                            isActive
                              ? "bg-yellow-600/20 border-yellow-500 text-slate-100"
                              : "bg-slate-800 border-slate-600 text-slate-400 hover:border-slate-500"
                          }`}
                          title="Click to activate, drag to another channel"
                        >
                          <Icons.Target
                            size={10}
                            className={isActive ? "text-yellow-400" : "text-slate-500"}
                          />
                          <span className="text-[10px] lowercase">{trg.mode || "trigger"}</span>
                          <span className="text-[10px] text-slate-500">
                            lvl {Number(trg.level || 0).toFixed(2)}
                          </span>
                          <button
                            onPointerDown={(e) => e.stopPropagation()}
                            onClick={(e) => {
                              e.stopPropagation();
                              onRemove?.(trg.id);
                            }}
                            className="ml-0.5 text-slate-500 hover:text-red-400 rounded transition-colors"
                            title="Remove trigger"
                          >
                            <Icons.X size={10} />
                          </button>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            );
          })
        )}
      </div>

      {dragState && (
        <div
          className="fixed z-[60] pointer-events-none flex items-center gap-1 px-1.5 py-0.5 rounded border border-yellow-500 bg-yellow-600/30 text-slate-100 shadow-lg"
          style={{ left: dragState.x + 8, top: dragState.y + 8 }}
        >
          <Icons.Target size={10} className="text-yellow-400" />
          <span className="text-[10px] lowercase">{dragState.mode || "trigger"}</span>
        </div>
      )}
    </div>
  );
};

export default TriggerMenu;