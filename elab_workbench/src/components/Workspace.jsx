import React, { memo } from 'react';
import { Icons } from '../utils/Shared.jsx';
import { WidgetHost } from './WidgetHost.jsx';

export const Workspace = memo(({
  gridClass,
  activeSlots,
  slots,
  offlineProviders,
  providers,
  handleDropOnSlot,
  handleUpdateTask,
  handleRemoveTask,
  handleAddChannel,
  onTouchDragStart,
  onTouchDragMove,
  onTouchDragEnd,
  onTouchDragCancel,
  streamBuffers,
  dispatcherClient,
}) => {
  return (
    <div className="flex-1 min-h-0 p-4 bg-[radial-gradient(ellipse_at_top_right,_var(--tw-gradient-stops))] from-slate-900 via-slate-950 to-black overflow-y-auto md:overflow-hidden">
      <div className={`grid gap-4 min-h-full h-auto md:h-full ${gridClass}`}>
        {activeSlots.map(i => {
          const task = slots[i];
          const isOffline = task && task.providerId && !task.is_recorded && (
            offlineProviders.has(task.providerId) ||
            !providers.some(p => p.id === task.providerId)
          );
          return (
            <div
              key={i}
              data-slot-index={i}
              onDragOver={e => e.preventDefault()}
              onDrop={e => handleDropOnSlot(e, i)}
              className={`relative rounded-lg transition-all duration-300 border-2 
                          ${task ? 'border-transparent bg-slate-800/50' : 'border-slate-800 border-dashed bg-slate-900/20 hover:border-slate-700'} 
                          overflow-hidden min-h-[18rem] md:min-h-0`}
            >
              {task ? (
                <WidgetHost
                  slotIndex={i}
                  task={task}
                  onUpdateTask={handleUpdateTask}
                  onRemove={handleRemoveTask}
                  onAddChannel={handleAddChannel}
                  onTouchDragStart={onTouchDragStart}
                  onTouchDragMove={onTouchDragMove}
                  onTouchDragEnd={onTouchDragEnd}
                  onTouchDragCancel={onTouchDragCancel}
                  streamBuffers={streamBuffers}
                  dispatcherClient={dispatcherClient}
                  isOffline={isOffline}
                />
              ) : (
                <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none">
                  <Icons.Plus size={24} strokeWidth={1.5} className="mb-1 text-slate-700" />
                  <span className="text-[10px] font-bold uppercase tracking-wider text-slate-700">Slot {i + 1}</span>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
});

Workspace.displayName = "Workspace";

