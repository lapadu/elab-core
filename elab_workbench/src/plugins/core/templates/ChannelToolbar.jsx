import React, { useRef } from "react";
import { Icons, preventFocusOnMouseDown } from "../../../utils/Shared";
import ChannelMenu from "./ChannelMenu";
import TriggerMenu from "./TriggerMenu";

/**
 * Generic channel + trigger indicator/menu pair, shared by any multi-channel
 * widget (Scope, Measure, ...). Renders the "N CH" pill (opens ChannelMenu)
 * and, when a trigger is active, the trigger pill (opens TriggerMenu).
 */
const ChannelToolbar = ({
  sources,
  onRemoveSource,
  onColorChange,
  onAction,
  onReorder,
  rawCaptureAwaiting = false,
  singleSource = false,
  channelMenuOpen,
  onToggleChannelMenu,
  onCloseChannelMenu,
  showTriggers = true,
  triggers = [],
  activeTrigger = null,
  triggerMenuOpen,
  onToggleTriggerMenu,
  onCloseTriggerMenu,
  onActivateTrigger,
  onMoveTrigger,
  onRemoveTrigger,
  onAddTriggerForChannel,
  className = "absolute top-2 left-2 z-40",
}) => {
  const channelAnchorRef = useRef(null);
  const triggerAnchorRef = useRef(null);

  if (!sources || sources.length === 0) return null;

  return (
    <div className={`${className} select-none`}>
      <div className="flex items-center gap-2">
        <button
          ref={channelAnchorRef}
          onMouseDown={preventFocusOnMouseDown}
          onClick={onToggleChannelMenu}
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

        {showTriggers && activeTrigger && (
          <button
            ref={triggerAnchorRef}
            onMouseDown={preventFocusOnMouseDown}
            onClick={onToggleTriggerMenu}
            className={`flex items-center gap-1.5 px-2 py-1 rounded-md text-[10px] font-bold uppercase tracking-wider transition-all ${
              triggerMenuOpen
                ? 'bg-slate-700 text-slate-200 shadow-lg'
                : 'bg-slate-900/60 text-slate-400 hover:bg-slate-800 hover:text-slate-200'
            }`}
            title="Open trigger menu"
          >
            <Icons.Target size={10} />
            <span className="truncate max-w-[90px]">{activeTrigger.mode || 'trigger'}{triggers.length > 1 ? ` +${triggers.length - 1}` : ''}</span>
            <Icons.ChevronDown size={10} className={`transition-transform ${triggerMenuOpen ? 'rotate-180' : ''}`} />
          </button>
        )}
      </div>

      {channelMenuOpen && (
        <ChannelMenu
          sources={sources}
          onRemoveSource={onRemoveSource}
          onColorChange={onColorChange}
          onAction={onAction}
          onReorder={onReorder}
          rawCaptureAwaiting={rawCaptureAwaiting}
          singleSource={singleSource}
          onClose={onCloseChannelMenu}
          anchorRef={channelAnchorRef}
        />
      )}

      {showTriggers && triggerMenuOpen && (
        <TriggerMenu
          triggers={triggers}
          activeTriggerId={activeTrigger?.id}
          channels={sources}
          onActivate={onActivateTrigger}
          onMove={onMoveTrigger}
          onRemove={onRemoveTrigger}
          onAddForChannel={onAddTriggerForChannel}
          onClose={onCloseTriggerMenu}
          anchorRef={triggerAnchorRef}
        />
      )}
    </div>
  );
};

export default ChannelToolbar;
