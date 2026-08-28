import React, { useState, memo, useMemo, useEffect, useRef, useCallback } from "react";
import { Icons } from "../utils/Shared.jsx";
import { RemoteWidgetLoader } from "./WidgetLoader.jsx";
import { PLUGIN_REGISTRY } from "./PluginRegistry.jsx";
import { factoryManager } from "../services/FactoryManager.js";
import { createRecordedBufferView } from "../utils/replayStreams.js";
import { taskSupportsTrigger, applyDroppedTrigger } from "../plugins/core/utils/configUtils.js";

const ErrorFallback = () => (
  <div className="text-red-500 p-2 text-xs">
    <Icons.AlertCircle className="inline mr-1" size={16} />
    Renderer not found
  </div>
);

const WidgetMenuPanel = ({ task, onUpdateTask, viewRenderers, activeRenderer, rendererProps }) => {
  const [showInfo, setShowInfo] = useState(false);

  const handleColorChange = (e) => {
    onUpdateTask({ ...task, color: e.target.value });
  };

  const handleNameChange = (e) => {
    onUpdateTask({ ...task, name: e.target.value });
  };

  const ConfigComponent = activeRenderer?.component;

  return (
    <div className="h-full p-4 bg-slate-900 overflow-y-auto custom-scrollbar">
      <div className="text-xs font-bold text-slate-500 uppercase mb-4 flex items-center gap-2">
        <Icons.Menu size={14} /> Widget Menu
      </div>

      <div className="space-y-3 text-xs">
        <div className="bg-slate-950 border border-slate-800 rounded-lg p-3">
          <label className="text-slate-400 block mb-2">Name</label>
          <input
            type="text"
            value={task.name || ""}
            onChange={handleNameChange}
            className="w-full bg-slate-900 text-slate-200 text-xs p-2 rounded border border-slate-700 focus:border-blue-500 outline-none"
          />
        </div>

        <div className="bg-slate-950 border border-slate-800 rounded-lg p-3">
          <label className="text-slate-400 block mb-2">Widget Color</label>
          <input
            type="color"
            value={task.color || "#3b82f6"}
            onChange={handleColorChange}
            className="w-full h-8 p-0 border-none rounded cursor-pointer bg-slate-800"
          />
        </div>

        {/* Plugin Configuration – rendered inline */}
        {ConfigComponent && (
          <div className="border border-slate-800 rounded-lg overflow-hidden">
            <ConfigComponent isConfigMode={true} {...rendererProps} />
          </div>
        )}

        {/* Collapsible Info Section */}
        <button
          onClick={() => setShowInfo((prev) => !prev)}
          className="w-full flex items-center justify-between mt-4 text-xs font-bold text-slate-500 uppercase hover:text-slate-400 transition-colors"
        >
          <span className="flex items-center gap-2">
            <Icons.Info size={14} /> Visual Info
          </span>
          {showInfo
            ? <Icons.ChevronDown size={14} />
            : <Icons.ChevronRight size={14} />
          }
        </button>

        {showInfo && (
          <div className="select-text bg-slate-950 border border-slate-800 rounded-lg p-3 font-mono text-[11px] text-slate-400 space-y-1">
            <div><span className="text-slate-500">Name:</span> {task.name}</div>
            <div><span className="text-slate-500">Type:</span> {task.type}</div>
            <div><span className="text-slate-500">Plugin:</span> {task.groupId}</div>
            <div><span className="text-slate-500">Provider:</span> {task.providerId || "-"}</div>
            <div><span className="text-slate-500">Task ID:</span> {task.id}</div>
            {task.originalId && <div><span className="text-slate-500">Original ID:</span> {task.originalId}</div>}
            <div><span className="text-slate-500">Views:</span> {viewRenderers.length}</div>
          </div>
        )}
      </div>
    </div>
  );
};

export const WidgetHost = memo(
  ({
    task,
    onUpdateTask,
    onRemove,
    onAddChannel,
    streamBuffers,
    dispatcherClient,
    isOffline,
    slotIndex,
    onTouchDragStart,
    onTouchDragMove,
    onTouchDragEnd,
    onTouchDragCancel,
  }) => {
    const widgetHostRef = useRef(null);
    const touchHeaderDragRef = useRef(null);
    const [showWidgetMenu, setShowWidgetMenu] = useState(false);
    const [focusMode, setFocusMode] = useState(false);
    const [isFullscreen, setIsFullscreen] = useState(false);
    const [activeViewId, setActiveViewId] = useState(() => {
      if (task.ui?.mode === "custom") return "custom";
      if (task.ui?.views?.length > 0) return task.ui.views[0].id;
      return "default";
    });

    const subscriberId = useMemo(
      () => `widget_slot_${slotIndex}_${task.id}`,
      [slotIndex, task.id],
    );

    const sourcePlugin = useMemo(
      () => PLUGIN_REGISTRY[task.groupId],
      [task.groupId],
    );

    const availableViews = useMemo(
      () => task.ui?.views || [],
      [task.ui?.views],
    );

    useEffect(() => {
      const taskId = task.originalId || task.id;
      if (task.ui?.isUiInstance) return;
      // A recorded task only ever renders replayed data.
      if (task.is_recorded) return;

      if (task.virtual && sourcePlugin && sourcePlugin.simulation) {
        factoryManager.startFactory(task, sourcePlugin);
        factoryManager.subscribe(taskId, subscriberId, () => {});
      }

      return () => {
        if (task.virtual && sourcePlugin && sourcePlugin.simulation) {
          factoryManager.unsubscribe(taskId, subscriberId);
        }
      };
    }, [task, subscriberId, sourcePlugin]);

    const viewRenderers = useMemo(() => {
      const renderers = [];
      if (task.ui?.mode === "custom") {
        renderers.push({
          id: "custom",
          component: RemoteWidgetLoader,
          label: "Custom",
          icon: "Code",
        });
      } else if (availableViews.length > 0) {
        availableViews.forEach((view) => {
          const TemplatePlugin = PLUGIN_REGISTRY[view.template];
          if (TemplatePlugin?.render) {
            renderers.push({
              id: view.id,
              component: TemplatePlugin.render,
              label: view.label,
              icon: view.icon,
            });
          } else {
            console.warn(
              `Template ${view.template} nicht gefunden für View ${view.id}`,
            );
          }
        });
      } else {
        const defaultTemplate = task.ui?.defaultTemplate || task.ui?.template;
        if (defaultTemplate) {
          const TemplatePlugin = PLUGIN_REGISTRY[defaultTemplate];
          if (TemplatePlugin?.render) {
            renderers.push({
              id: "default",
              component: TemplatePlugin.render,
              label: "Default",
              icon: "Layout",
            });
          }
        }
      }

      if (renderers.length === 0) {
        renderers.push({
          id: "error",
          component: ErrorFallback,
          label: "Error",
          icon: "AlertCircle",
        });
      }
      return renderers;
    }, [task.ui, availableViews]);

    // A recorded task must behave like its own source: the replayer publishes
    // under "rec_*" ids while templates still look data up by the live id.
    // Only that one id is shadowed, so live channels can still be added to a
    // replay widget on purpose.
    const effectiveStreamBuffers = useMemo(
      () =>
        task.is_recorded
          ? createRecordedBufferView(streamBuffers, task.originalId)
          : streamBuffers,
      [streamBuffers, task.is_recorded, task.originalId],
    );

    const wrappedOnUpdateTask = useCallback(
      (updatedTask) => {
        if (onUpdateTask) onUpdateTask(slotIndex, updatedTask);
      },
      [onUpdateTask, slotIndex]
    );

    const wrappedOnRemove = useCallback(() => {
      if (onRemove) onRemove(slotIndex);
    }, [onRemove, slotIndex]);

    const wrappedOnAddChannel = useCallback(
      (droppedTask) => {
        if (onAddChannel) onAddChannel(slotIndex, droppedTask);
      },
      [onAddChannel, slotIndex]
    );

    const rendererProps = useMemo(
      () => ({
        task,
        onUpdateTask: wrappedOnUpdateTask,
        onRemove: wrappedOnRemove,
        streamBuffers: effectiveStreamBuffers,
        dispatcherClient,
        sourcePlugin,
        onSubTaskDrop: wrappedOnAddChannel,
        dataStreams: effectiveStreamBuffers
          ? Object.fromEntries(
              Array.from(effectiveStreamBuffers.entries()).map(([id, buffer]) => [
                id,
                { value: buffer.getLatest?.() ?? null, buffer },
              ]),
            )
          : {},
      }),
      [
        task,
        wrappedOnUpdateTask,
        wrappedOnRemove,
        effectiveStreamBuffers,
        dispatcherClient,
        sourcePlugin,
        wrappedOnAddChannel,
      ],
    );

    const createDragPayload = useCallback(() => {
      // For recorded tasks keep the rec_* id so downstream widgets subscribe
      // to the replay stream, not to a live source that may share the
      // original id.
      return task.is_recorded
        ? { ...task }
        : { ...task, id: task.originalId || task.id };
    }, [task]);

    const handleDragStart = (e) => {
      // For recorded tasks keep the rec_* id so downstream widgets subscribe
      // to the replay stream, not to a live source that may share the
      // original id.
      const dragPayload = createDragPayload();
      e.dataTransfer.setData("task", JSON.stringify(dragPayload));
      e.dataTransfer.effectAllowed = "copy";
    };

    /** @param {React.TouchEvent} e */
    const handleHeaderTouchStart = useCallback((e) => {
      if (e.touches.length !== 1) return;

      const touch = e.touches[0];
      touchHeaderDragRef.current = {
        startX: touch.clientX,
        startY: touch.clientY,
        payload: createDragPayload(),
        dragging: false,
      };
    }, [createDragPayload]);

    /** @param {React.TouchEvent} e */
    const handleHeaderTouchMove = useCallback((e) => {
      const state = touchHeaderDragRef.current;
      if (!state || e.touches.length !== 1) return;

      const touch = e.touches[0];
      const point = { x: touch.clientX, y: touch.clientY };
      const movement = Math.hypot(point.x - state.startX, point.y - state.startY);

      if (!state.dragging && movement < 10) return;

      if (!state.dragging) {
        state.dragging = true;
        onTouchDragStart?.(state.payload, point);
      } else {
        onTouchDragMove?.(point);
      }

      e.preventDefault();
      e.stopPropagation();
    }, [onTouchDragMove, onTouchDragStart]);

    /** @param {React.TouchEvent} e */
    const handleHeaderTouchEnd = useCallback((e) => {
      const state = touchHeaderDragRef.current;
      touchHeaderDragRef.current = null;
      if (!state?.dragging) return;

      const touch = e.changedTouches[0];
      if (!touch) {
        onTouchDragCancel?.();
        return;
      }

      onTouchDragEnd?.({ x: touch.clientX, y: touch.clientY });
      e.preventDefault();
      e.stopPropagation();
    }, [onTouchDragCancel, onTouchDragEnd]);

    const handleHeaderTouchCancel = useCallback((e) => {
      const state = touchHeaderDragRef.current;
      touchHeaderDragRef.current = null;
      if (state?.dragging) {
        onTouchDragCancel?.();
      }
      e.preventDefault();
      e.stopPropagation();
    }, [onTouchDragCancel]);

    // Intercept drops on MEASURE tasks: wire the sensor as inputs.source
    const handleWidgetDrop = useCallback((e) => {
      const dataStr = e.dataTransfer.getData("task");
      if (!dataStr) return;

      try {
        const droppedTask = JSON.parse(dataStr);
        if (droppedTask.id === task.id) return;

        const isTrigger = droppedTask.type === 'TRIGGER';
        const isTriggerSupported = isTrigger && taskSupportsTrigger(task);

        if (!isTriggerSupported && task.type !== "MEASURE") return;

        e.preventDefault();
        e.stopPropagation();

        if (isTrigger) {
          wrappedOnUpdateTask(applyDroppedTrigger(task, droppedTask));
          return;
        }

        if (!task.inputs?.source) {
          wrappedOnUpdateTask({ ...task, inputs: { ...task.inputs, source: droppedTask } });
        } else {
          // Primary source already set — add as extra channel.
          const extra = task.extraChannels || [];
          if (!extra.find((c) => c.id === droppedTask.id)) {
            wrappedOnUpdateTask({ ...task, extraChannels: [...extra, droppedTask] });
          }
        }
      } catch (err) {
        console.error("Error handling drop on widget:", err);
      }
    }, [task, wrappedOnUpdateTask]);

    const handleWidgetDragOver = useCallback((e) => {
      if (task.type === "MEASURE" || taskSupportsTrigger(task)) {
        e.preventDefault();
        e.stopPropagation();
      }
    }, [task]);

    const handleFullscreen = () => {
        if (!widgetHostRef.current) return;
        if (document.fullscreenElement === widgetHostRef.current) {
            document.exitFullscreen();
        } else {
            widgetHostRef.current.requestFullscreen().catch(err => {
                console.error(`Error attempting to enable full-screen mode: ${err.message} (${err.name})`);
            });
        }
    };

    useEffect(() => {
        const handleFullscreenChange = () => {
            setIsFullscreen(document.fullscreenElement === widgetHostRef.current);
        };
        document.addEventListener('fullscreenchange', handleFullscreenChange);
        return () => document.removeEventListener('fullscreenchange', handleFullscreenChange);
    }, []);

    const mainRenderer = viewRenderers[0] || null;
    const satelliteRenderers = viewRenderers.slice(1, 6);
    const hasCombinedView = viewRenderers.length > 1;
    const isFocusModeActive = hasCombinedView && focusMode;

    return (
      <div
        ref={widgetHostRef}
        data-widget-slot-index={slotIndex}
        data-widget-type={task.type}
        onDragOver={handleWidgetDragOver}
        onDrop={handleWidgetDrop}
        className={`relative h-full bg-slate-900 rounded-lg border overflow-hidden flex flex-col ${
          focusMode
            ? "border-amber-400 shadow-[0_0_0_2px_rgba(251,191,36,0.5)]"
            : "border-slate-800"
        }`}
      >
        {/* HEADER DESKTOP */}
        <div className="hidden md:flex h-8 bg-slate-950/50 border-b border-slate-800 items-center justify-between px-3 shrink-0 z-[60] relative">
          <div
            className="flex items-center gap-2 min-w-0 cursor-grab active:cursor-grabbing"
            draggable={true}
            onDragStart={handleDragStart}
            onTouchStart={handleHeaderTouchStart}
            onTouchMove={handleHeaderTouchMove}
            onTouchEnd={handleHeaderTouchEnd}
            onTouchCancel={handleHeaderTouchCancel}
          >
            <div
              className="w-2 h-2 rounded-full shrink-0"
              style={{ backgroundColor: task.color }}
            />
            <span className="text-xs font-bold text-slate-300 truncate">
              {task.name}
            </span>
            {task.extraChannels?.length > 0 && (
              <span
                className="text-[9px] bg-slate-800 text-slate-400 px-1.5 py-0.5 rounded-full font-bold ml-1"
                title={`${task.extraChannels.length} additional channel(s) attached`}
              >
                +{task.extraChannels.length} CH
              </span>
            )}
            {task.virtual && (
              <Icons.Cpu className="text-slate-600 shrink-0" size={10} />
            )}
          </div>

          <div className="flex items-center gap-1">
            {viewRenderers.length > 1 && (
              <div
                role="tablist"
                aria-label={`Ansichten für ${task.name || 'Widget'}`}
                className="flex gap-0.5 bg-slate-900 rounded p-0.5 mr-1"
              >
                {viewRenderers.map((renderer) => {
                  const IconComponent = Icons[renderer.icon] || Icons.Layout;
                  const isActive = activeViewId === renderer.id;
                  return (
                    <button
                      key={renderer.id}
                      type="button"
                      role="tab"
                      aria-selected={isActive}
                      aria-label={renderer.label}
                      onClick={() => setActiveViewId(renderer.id)}
                      className={`p-1 rounded transition-colors ${
                        isActive
                          ? "bg-slate-700 text-slate-200"
                          : "text-slate-500 hover:text-slate-300 hover:bg-slate-800"
                      }`}
                      title={renderer.label}
                    >
                      <IconComponent size={12} />
                    </button>
                  );
                })}
              </div>
            )}

            {hasCombinedView ? (
              <button
                onClick={() => setFocusMode((prev) => !prev)}
                className={`p-1 rounded transition-colors ${
                  isFocusModeActive
                    ? "bg-amber-500/20 text-amber-300"
                    : "hover:bg-slate-700 text-slate-400 hover:text-slate-200"
                }`}
                title="Focus Mode"
              >
                <Icons.Table size={14} />
              </button>
            ) : (
              <span
                className="p-1 rounded invisible"
                aria-hidden="true"
              >
                <Icons.Table size={14} />
              </span>
            )}

            <button
                onClick={handleFullscreen}
                className="p-1 rounded hover:bg-slate-700 text-slate-400 hover:text-slate-200 transition-colors"
                title={isFullscreen ? "Exit Fullscreen" : "Fullscreen"}
            >
                {isFullscreen ? <Icons.Minimize size={14} /> : <Icons.Maximize size={14} />}
            </button>

            {/* Recorded tasks are read-only – hide the settings menu */}
            {!task.is_recorded && (
            <button
              onClick={() => {
                setShowWidgetMenu((prev) => !prev);
                setFocusMode(false);
              }}
              className={`p-1 rounded transition-colors ${
                showWidgetMenu
                  ? "bg-slate-700 text-slate-200"
                  : "hover:bg-slate-700 text-slate-400 hover:text-slate-200"
              }`}
              title="Widget Menu"
            >
              <Icons.Menu size={14} />
            </button>
            )}

            <button
              onClick={wrappedOnRemove}
              className="p-1 rounded hover:bg-red-900 text-slate-400 hover:text-red-400 transition-colors"
              title="Remove"
            >
              <Icons.X size={14} />
            </button>
          </div>
        </div>

        {/* HEADER MOBILE */}
        <div className="md:hidden bg-slate-950/50 border-b border-slate-800 px-2 py-1.5 shrink-0 z-[60] relative space-y-1">
          <div
            className="flex items-center gap-2 min-w-0 rounded bg-slate-900/60 px-2 py-1.5 active:bg-slate-800/80"
            draggable={true}
            onDragStart={handleDragStart}
            onTouchStart={handleHeaderTouchStart}
            onTouchMove={handleHeaderTouchMove}
            onTouchEnd={handleHeaderTouchEnd}
            onTouchCancel={handleHeaderTouchCancel}
          >
            <div
              className="w-2 h-2 rounded-full shrink-0"
              style={{ backgroundColor: task.color }}
            />
            <span className="text-xs font-bold text-slate-300 truncate">
              {task.name}
            </span>
            {task.extraChannels?.length > 0 && (
              <span
                className="text-[9px] bg-slate-800 text-slate-400 px-1.5 py-0.5 rounded-full font-bold ml-1"
                title={`${task.extraChannels.length} additional channel(s) attached`}
              >
                +{task.extraChannels.length} CH
              </span>
            )}
            {task.virtual && (
              <Icons.Cpu className="text-slate-600 shrink-0" size={10} />
            )}
          </div>

          <div className="flex items-center justify-between gap-1">
            <div className="flex items-center gap-1 min-w-0 overflow-x-auto custom-scrollbar">
              {viewRenderers.length > 1 && (
                <div
                  role="tablist"
                  aria-label={`Ansichten für ${task.name || 'Widget'}`}
                  className="flex gap-0.5 bg-slate-900 rounded p-0.5"
                >
                  {viewRenderers.map((renderer) => {
                    const IconComponent = Icons[renderer.icon] || Icons.Layout;
                    const isActive = activeViewId === renderer.id;
                    return (
                      <button
                        key={renderer.id}
                        type="button"
                        role="tab"
                        aria-selected={isActive}
                        aria-label={renderer.label}
                        onClick={() => setActiveViewId(renderer.id)}
                        className={`p-1 rounded transition-colors ${
                          isActive
                            ? "bg-slate-700 text-slate-200"
                            : "text-slate-500 hover:text-slate-300 hover:bg-slate-800"
                        }`}
                        title={renderer.label}
                      >
                        <IconComponent size={12} />
                      </button>
                    );
                  })}
                </div>
              )}
            </div>

            <div className="flex items-center gap-1 shrink-0">
              {hasCombinedView ? (
                <button
                  onClick={() => setFocusMode((prev) => !prev)}
                  className={`p-1 rounded transition-colors ${
                    isFocusModeActive
                      ? "bg-amber-500/20 text-amber-300"
                      : "hover:bg-slate-700 text-slate-400 hover:text-slate-200"
                  }`}
                  title="Focus Mode"
                >
                  <Icons.Table size={14} />
                </button>
              ) : (
                <span className="p-1 rounded invisible" aria-hidden="true">
                  <Icons.Table size={14} />
                </span>
              )}

              <button
                  onClick={handleFullscreen}
                  className="p-1 rounded hover:bg-slate-700 text-slate-400 hover:text-slate-200 transition-colors"
                  title={isFullscreen ? "Exit Fullscreen" : "Fullscreen"}
              >
                  {isFullscreen ? <Icons.Minimize size={14} /> : <Icons.Maximize size={14} />}
              </button>

              {!task.is_recorded && (
              <button
                onClick={() => {
                  setShowWidgetMenu((prev) => !prev);
                  setFocusMode(false);
                }}
                className={`p-1 rounded transition-colors ${
                  showWidgetMenu
                    ? "bg-slate-700 text-slate-200"
                    : "hover:bg-slate-700 text-slate-400 hover:text-slate-200"
                }`}
                title="Widget Menu"
              >
                <Icons.Menu size={14} />
              </button>
              )}

              <button
                onClick={wrappedOnRemove}
                className="p-1 rounded hover:bg-red-900 text-slate-400 hover:text-red-400 transition-colors"
                title="Remove"
              >
                <Icons.X size={14} />
              </button>
            </div>
          </div>
        </div>

        {/* CONTENT */}
        <div className={`relative flex-1 min-h-0 ${isOffline ? "grayscale opacity-20" : ""}`}>
          {showWidgetMenu ? (
            <WidgetMenuPanel
              task={task}
              onUpdateTask={(updatedTask) => wrappedOnUpdateTask(updatedTask)}
              viewRenderers={viewRenderers}
              activeRenderer={viewRenderers.find((r) => r.id === activeViewId) || viewRenderers[0]}
              rendererProps={rendererProps}
            />
          ) : isFocusModeActive && mainRenderer ? (
            <div className="grid-5x1-layout grid gap-2 h-full p-2">
              <div className="rounded border border-slate-800 overflow-hidden bg-slate-950">
                <mainRenderer.component isConfigMode={false} {...rendererProps} />
              </div>

              {satelliteRenderers.map((renderer) => {
                const RendererComponent = renderer.component;
                return (
                  <div key={renderer.id} className="rounded border border-slate-800 overflow-hidden bg-slate-950 relative">
                    <div className="absolute top-1 left-1 z-10 text-[9px] font-bold uppercase tracking-wider bg-slate-900/80 text-slate-300 px-1.5 py-0.5 rounded">
                      {renderer.label}
                    </div>
                    <RendererComponent isConfigMode={false} {...rendererProps} />
                  </div>
                );
              })}
            </div>
          ) : (
            viewRenderers.map((renderer) => {
              const RendererComponent = renderer.component;
              const isActive = renderer.id === activeViewId;

              return (
                <div
                  key={renderer.id}
                  className={`h-full w-full ${isActive ? "block" : "hidden"}`}
                >
                  <RendererComponent isConfigMode={false} {...rendererProps} />
                </div>
              );
            })
          )}
        </div>

        {/* OFFLINE OVERLAY */}
        {isOffline && (
          <div className="absolute inset-0 z-50 bg-slate-950/80 backdrop-blur-[2px] flex flex-col items-center justify-center">
            <div className="bg-red-500/10 p-4 rounded-full mb-3 border border-red-500/20 animate-pulse">
              <Icons.WifiOff className="text-red-500" size={32} />
            </div>
            <h3 className="text-red-400 font-bold tracking-widest uppercase">
              Connection Lost
            </h3>
            <p className="text-xs text-red-500/70 font-mono mt-1">
              Provider Offline
            </p>
            <button
              onClick={wrappedOnRemove}
              className="mt-4 px-3 py-1.5 rounded bg-slate-800 hover:bg-red-900 text-slate-400 hover:text-red-400 text-xs font-bold uppercase tracking-wider transition-colors border border-slate-700 hover:border-red-800"
              title="Remove Widget"
            >
              <Icons.X size={12} className="inline mr-1" />
              Remove
            </button>
          </div>
        )}
      </div>
    );
  },
);

WidgetHost.displayName = "WidgetHost";
