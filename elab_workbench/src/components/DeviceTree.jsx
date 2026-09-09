import React, { useRef, useState, memo } from "react";
import { Icons, displayName } from "../utils/Shared";

const generateInstanceId = () => `inst_${Date.now()}`;

const STORAGE_KEY_TREE_EXPANDED = "elab.v1.tree_expanded";
const STORAGE_KEY_TAG_FILTERS = "elab.v1.tag_filters";
const STORAGE_KEY_TAGS_EXPANDED = "elab.v1.tags_expanded";
const STORAGE_KEY_TREE_GROUPING = "elab.v1.tree_grouping";

const loadExpandedState = () => {
  try {
    const saved = localStorage.getItem(STORAGE_KEY_TREE_EXPANDED);
    return saved
      ? JSON.parse(saved)
      : {
          Sensors: true,
          Actuators: true,
          Generators: true,
          Math: true,
          Measures: true,
          Recorded: true,
          Triggers: true,
          Library: true,
        };
  } catch (error) {
    console.error("Failed to load expanded state:", error);
    return {
      Sensors: true,
      Actuators: true,
      Generators: true,
      Math: true,
      Measures: true,
      Recorded: true,
      Triggers: true,
      Library: true,
    };
  }
};

const saveExpandedState = (state) => {
  try {
    localStorage.setItem(STORAGE_KEY_TREE_EXPANDED, JSON.stringify(state));
  } catch (error) {
    console.error("Failed to save expanded state:", error);
  }
};

/**
 * @param {{
 *  devices: Record<string, import('../plugins/core/ManifestTypes').Task[]>,
 *  scripts: any[],
 *  onStartScript: (filename: string) => void,
 *  onStopScript: (filename: string) => void,
 *  onTouchDragStart?: (task: import('../plugins/core/ManifestTypes').Task, point: { x: number, y: number }) => void,
 *  onTouchDragMove?: (point: { x: number, y: number }) => void,
 *  onTouchDragEnd?: (point: { x: number, y: number }) => void,
 *  onTouchDragCancel?: () => void
 * }} props
 */
export const DeviceTree = memo(
  ({
    devices,
    scripts = [],
    pendingDevices = [],
    onApproveDevice,
    onRevokeDevice,
    onStartScript,
    onStopScript,
    onTouchDragStart,
    onTouchDragMove,
    onTouchDragEnd,
    onTouchDragCancel,
  }) => {
    const touchDragStateRef = useRef(null);
    const [expanded, setExpandedLocal] = useState(() => loadExpandedState());
    const [treeGrouping, setTreeGroupingLocal] = useState(() => {
      try {
        return localStorage.getItem(STORAGE_KEY_TREE_GROUPING) || "category";
      } catch (error) {
        console.warn("Failed to load tree grouping:", error);
        return "category";
      }
    });
    const [tagFilters, setTagFiltersLocal] = useState(() => {
      try {
        const saved = localStorage.getItem(STORAGE_KEY_TAG_FILTERS);
        return saved ? new Set(JSON.parse(saved)) : new Set();
      } catch (error) {
        console.warn("Failed to load tag filters:", error);
        return new Set();
      }
    });
    const [isTagsExpanded, setIsTagsExpandedLocal] = useState(() => {
      try {
        const saved = localStorage.getItem(STORAGE_KEY_TAGS_EXPANDED);
        return saved !== null ? JSON.parse(saved) : false;
      } catch (error) {
        console.warn("Failed to load tags expanded state:", error);
        return false;
      }
    });

    const setTreeGrouping = (value) => {
      setTreeGroupingLocal(value);
      try {
        localStorage.setItem(STORAGE_KEY_TREE_GROUPING, value);
      } catch (error) {
        console.warn("Failed to save tree grouping:", error);
      }
    };

    const setIsTagsExpanded = (updater) => {
      setIsTagsExpandedLocal((prev) => {
        const next = typeof updater === "function" ? updater(prev) : updater;
        try {
          localStorage.setItem(STORAGE_KEY_TAGS_EXPANDED, JSON.stringify(next));
        } catch (error) {
          console.warn("Failed to save tags expanded state:", error);
        }
        return next;
      });
    };

    const toggleTagFilter = (tag) => {
      setTagFiltersLocal((prev) => {
        const next = new Set(prev);
        if (next.has(tag)) next.delete(tag);
        else next.add(tag);
        try {
          localStorage.setItem(STORAGE_KEY_TAG_FILTERS, JSON.stringify([...next]));
        } catch (error) {
          console.warn("Failed to save tag filters:", error);
        }
        return next;
      });
    };

    const clearTagFilters = () => {
      setTagFiltersLocal(new Set());
      try {
        localStorage.setItem(STORAGE_KEY_TAG_FILTERS, '[]');
      } catch (error) {
        console.warn("Failed to reset tag filters:", error);
      }
    };

    const setExpanded = (updater) => {
      setExpandedLocal((prev) => {
        const next = typeof updater === "function" ? updater(prev) : updater;
        saveExpandedState(next);
        return next;
      });
    };

    const getTypeInfo = (type) => {
      const t = (type || "").toUpperCase();
      switch (t) {
        case "ACTUATOR":
          return {
            icon: Icons.Zap,
            color: "text-blue-500",
            filterKey: "ACTUATOR",
            label: "Actuator",
          };
        case "MATH":
          return {
            icon: Icons.Calculator,
            color: "text-purple-500",
            filterKey: "MATH",
            label: "Math",
          };
        case "MEASURE":
          return {
            icon: Icons.Sigma,
            color: "text-orange-500",
            filterKey: "MEASURE",
            label: "Measure",
          };
        case "TRIGGER":
          return {
            icon: Icons.Target,
            color: "text-yellow-500",
            filterKey: "TRIGGER",
            label: "Trigger",
          };
        case "CONTROL":
          return {
            icon: Icons.Settings,
            color: "text-rose-500",
            filterKey: "CONTROL",
            label: "Control",
          };
        case "GENERATOR":
          return {
            icon: Icons.Radio,
            color: "text-cyan-500",
            filterKey: "GENERATOR",
            label: "Generator",
          };
        case "SENSOR":
        default:
          return {
            icon: Icons.Activity,
            color: "text-emerald-500",
            filterKey: "SENSOR",
            label: "Sensor",
          };
      }
    };

    const filterByTags = (items) => {
      if (tagFilters.size === 0) return items;
      return items.filter((dev) => {
        const devTags = dev.tags || [];
        return [...tagFilters].every((tag) => devTags.includes(tag));
      });
    };

    const filterList = (items) => {
      return filterByTags(items);
    };

    /** Collect all unique tags across all registered tasks. */
    const collectVisibleTags = () => {
      const tags = new Set();
      Object.values(devices).forEach((items) => {
        items.forEach((dev) => {
          (dev.tags || []).forEach((t) => tags.add(t));
        });
      });
      return [...tags].sort();
    };

    const visibleTags = collectVisibleTags();

    const deviceGroups = Object.values(devices)
      .flatMap((items) => filterList(items))
      .reduce((groups, task) => {
        const deviceId = task.deviceId || task.providerId || task.id;
        const providerId = task.providerId || task.id;
        const device = groups.get(deviceId) || {
          id: deviceId,
          name: task.deviceName || deviceId,
          anchor: task.deviceAnchor,
          providers: new Map(),
        };
        const provider = device.providers.get(providerId) || { id: providerId, tasks: [] };
        provider.tasks.push(task);
        device.providers.set(providerId, provider);
        groups.set(deviceId, device);
        return groups;
      }, new Map());

    const getRelevantKeys = () => {
      if (treeGrouping === "device") {
        return [...[...deviceGroups.values()].map((d) => `device:${d.id}`), "Library"];
      }
      return [...Object.keys(devices), "Library"];
    };

    const getExpandedState = () => {
      const keys = getRelevantKeys();
      if (keys.length === 0) return "collapsed";
      const allExpanded = keys.every((k) => expanded[k] ?? true);
      const allCollapsed = keys.every((k) => expanded[k] === false);

      if (allExpanded) return "expanded";
      if (allCollapsed) return "collapsed";
      return "mixed";
    };

    const handleToggleExpandAll = () => {
      const keys = getRelevantKeys();
      const state = getExpandedState();
      const shouldExpand = state !== "expanded";

      setExpanded((prev) => {
        const next = { ...prev };
        keys.forEach((key) => {
          next[key] = shouldExpand;
        });
        return next;
      });
    };

    const buildDragPayload = (dev) => {
      const taskData = dev.isFactory ? dev.createTask() : dev;

      return {
        id: dev.isFactory ? generateInstanceId() : taskData.id,
        originalId: dev.isFactory ? taskData.id : taskData.originalId,
        groupId: taskData.groupId,
        name: taskData.name,
        type: taskData.type,
        virtual: !!taskData.virtual,
        is_recorded: !!taskData.is_recorded,
        providerId: taskData.providerId,
        config: taskData.config || {},
        ui: taskData.ui || {},
        color: taskData.color,
        inputs: taskData.inputs || {},
        actions: taskData.actions || [],
      };
    };

    /**
     * @param {React.DragEvent} e
     * @param {import('../plugins/core/ManifestTypes').Task} dev
     */
    const handleDragStart = (e, dev) => {
      try {
        const cleanPayload = buildDragPayload(dev);
        const jsonStr = JSON.stringify(cleanPayload);
        e.dataTransfer.setData("task", jsonStr);
        e.dataTransfer.effectAllowed = "copy";
      } catch (error) {
        console.error("Error in drag start:", error);
        e.preventDefault();
      }
    };

    /**
     * @param {React.TouchEvent} e
     * @param {import('../plugins/core/ManifestTypes').Task} dev
     */
    const handleTouchStart = (e, dev) => {
      if (e.touches.length !== 1) return;
      const touch = e.touches[0];
      touchDragStateRef.current = {
        startX: touch.clientX,
        startY: touch.clientY,
        payload: buildDragPayload(dev),
        dragging: false,
      };
    };

    /** @param {React.TouchEvent} e */
    const handleTouchMove = (e) => {
      const state = touchDragStateRef.current;
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
    };

    /** @param {React.TouchEvent} e */
    const handleTouchEnd = (e) => {
      const state = touchDragStateRef.current;
      touchDragStateRef.current = null;
      if (!state?.dragging) return;

      const touch = e.changedTouches[0];
      if (!touch) {
        onTouchDragCancel?.();
        return;
      }

      onTouchDragEnd?.({ x: touch.clientX, y: touch.clientY });
      e.preventDefault();
    };

    const handleTouchCancel = () => {
      const state = touchDragStateRef.current;
      touchDragStateRef.current = null;
      if (state?.dragging) {
        onTouchDragCancel?.();
      }
    };

    const expandedState = getExpandedState();
    const isExpanded = expandedState === "expanded";

    return (
      <div className="p-3 space-y-3">
        {/* ROW 1: TOOLBAR (EXPAND/COLLAPSE & GROUPING) */}
        <div className="flex items-center justify-between gap-1 bg-slate-900/95 p-1 rounded-lg border border-slate-800 shadow-sm">
          {/* Left: Expand/Collapse All */}
          <button
            type="button"
            onClick={handleToggleExpandAll}
            className={`h-7 w-7 shrink-0 rounded transition-all flex items-center justify-center border border-transparent ${
              isExpanded
                ? "text-slate-300 bg-slate-800 hover:bg-slate-700"
                : "text-slate-400 hover:text-slate-200 hover:bg-slate-800"
            }`}
            title={isExpanded ? "Collapse all" : "Expand all"}
            aria-label={isExpanded ? "Collapse all" : "Expand all"}
          >
            {isExpanded ? (
              <Icons.ListCollapse size={13} className="text-slate-300" />
            ) : (
              <Icons.ListChevronsUpDown size={13} className="text-slate-400" />
            )}
          </button>

          {/* Right: Grouping Segmented Switcher (Category / Device) */}
          <div className="flex min-w-0 shrink-0 items-center bg-slate-950/80 p-px rounded-md border border-slate-800/80">
            <button
              type="button"
              onClick={() => setTreeGrouping("category")}
              className={`px-2 py-1 rounded text-[10px] font-medium transition-all flex items-center gap-1 ${
                treeGrouping === "category"
                  ? "bg-slate-700 text-white shadow-sm font-semibold"
                  : "text-slate-400 hover:text-slate-200 hover:bg-slate-800/40"
              }`}
              title="Group by category"
              aria-label="Group by category"
            >
              <Icons.Layers size={11} />
              <span>Category</span>
            </button>
            <button
              type="button"
              onClick={() => setTreeGrouping("device")}
              className={`px-2 py-1 rounded text-[10px] font-medium transition-all flex items-center gap-1 ${
                treeGrouping === "device"
                  ? "bg-slate-700 text-white shadow-sm font-semibold"
                  : "text-slate-400 hover:text-slate-200 hover:bg-slate-800/40"
              }`}
              title="Group by device"
              aria-label="Group by device"
            >
              <Icons.Server size={11} />
              <span>Device</span>
            </button>
          </div>
        </div>

        {/* ROW 2: TAGS AS EXTRA ZEILE UNTER CATEGORY UND DEVICES */}
        {visibleTags.length > 0 && (
          <div className="bg-slate-900/95 rounded-lg border border-slate-800 overflow-hidden shadow-sm">
            <button
              type="button"
              onClick={() => setIsTagsExpanded((prev) => !prev)}
              className="w-full h-7 px-2.5 flex items-center justify-between text-[11px] font-medium text-slate-400 hover:text-slate-200 hover:bg-slate-800/60 transition-colors cursor-pointer"
              aria-expanded={isTagsExpanded}
            >
              <div className="flex items-center gap-1.5">
                <Icons.Tag size={12} className={tagFilters.size > 0 ? "text-sky-400" : "text-slate-400"} />
                <span className="text-slate-300">Tags</span>
                <span className="text-[10px] text-slate-500 font-normal">({visibleTags.length})</span>
                {tagFilters.size > 0 && (
                  <span className="bg-sky-500 text-slate-950 font-bold text-[9px] px-1.5 rounded-full leading-tight ml-1">
                    {tagFilters.size} active
                  </span>
                )}
              </div>

              <div className="flex items-center gap-2">
                {tagFilters.size > 0 && (
                  <span
                    onClick={(e) => {
                      e.stopPropagation();
                      clearTagFilters();
                    }}
                    className="text-[10px] text-sky-400 hover:text-sky-300 underline cursor-pointer"
                  >
                    Clear
                  </span>
                )}
                {isTagsExpanded ? (
                  <Icons.ChevronDown size={12} className="text-slate-400" />
                ) : (
                  <Icons.ChevronRight size={12} className="text-slate-400" />
                )}
              </div>
            </button>

            {/* Tags Selection Area (when expanded) */}
            {isTagsExpanded && (
              <div className="p-2 border-t border-slate-800/80 bg-slate-950/40">
                <div className="flex flex-wrap gap-1 max-h-40 overflow-y-auto custom-scrollbar">
                  {visibleTags.map((tag) => {
                    const active = tagFilters.has(tag);
                    return (
                      <button
                        key={tag}
                        type="button"
                        onClick={() => toggleTagFilter(tag)}
                        className={`px-2 py-0.5 rounded text-[9px] font-medium transition-all border cursor-pointer ${
                          active
                            ? "bg-sky-600 text-white border-sky-500 shadow-sm"
                            : "bg-slate-800/90 text-slate-400 border-slate-700/60 hover:text-slate-200 hover:border-slate-600"
                        }`}
                      >
                        {tag}
                      </button>
                    );
                  })}
                </div>
              </div>
            )}

            {/* Active Tag Filter Chips (when collapsed but tags are active) */}
            {!isTagsExpanded && tagFilters.size > 0 && (
              <div className="px-2.5 py-1.5 border-t border-slate-800/80 bg-slate-950/40 flex items-center gap-1 flex-wrap text-[9px]">
                <span className="text-slate-500 text-[9px]">Filtered:</span>
                {[...tagFilters].map((tag) => (
                  <span
                    key={tag}
                    className="inline-flex items-center gap-1 bg-sky-950/90 border border-sky-800/80 text-sky-300 px-1.5 py-0.5 rounded text-[9px]"
                  >
                    {tag}
                    <button
                      type="button"
                      onClick={() => toggleTagFilter(tag)}
                      className="hover:text-white font-bold leading-none ml-0.5 cursor-pointer"
                      title={`Remove tag ${tag}`}
                    >
                      ×
                    </button>
                  </span>
                ))}
              </div>
            )}
          </div>
        )}

        {/* DEVICE LISTS */}
        {treeGrouping === "category" && Object.entries(devices).map(([category, rawItems]) => {
          const items = filterList(rawItems);

          if (
            items.length === 0 &&
            rawItems.length > 0 &&
            tagFilters.size > 0
          )
            return null;

          return (
            <div key={category}>
              <button
                type="button"
                className="w-full flex items-center gap-2 text-slate-400 text-xs font-bold uppercase tracking-widest cursor-pointer hover:text-slate-200 mb-2"
                aria-expanded={!!expanded[category]}
                aria-controls={`elab-devicetree-section-${category}`}
                onClick={() =>
                  setExpanded((p) => ({ ...p, [category]: !p[category] }))
                }
              >
                {expanded[category] ? (
                  <Icons.ChevronDown size={12} />
                ) : (
                  <Icons.ChevronRight size={12} />
                )}
                {category} ({items.length})
              </button>

              {expanded[category] && (
                <div
                  id={`elab-devicetree-section-${category}`}
                  className="space-y-1 pl-2 border-l border-slate-800 ml-1.5"
                >
                  {items.map((dev) => {
                    const { icon: TypeIcon, color } = getTypeInfo(dev.type);
                    return (
                      <div
                        key={dev.id}
                        draggable
                        onDragStart={(e) => handleDragStart(e, dev)}
                        onTouchStart={(e) => handleTouchStart(e, dev)}
                        onTouchMove={handleTouchMove}
                        onTouchEnd={handleTouchEnd}
                        onTouchCancel={handleTouchCancel}
                        className="group flex items-center justify-between p-2 rounded bg-slate-900 border border-transparent hover:border-slate-700 cursor-grab active:cursor-grabbing hover:shadow-md transition-all"
                      >
                        <div className="flex items-center gap-2 overflow-hidden">
                          <TypeIcon size={14} className={color} />
                          <div className="overflow-hidden min-w-0">
                            <div
                              className="text-xs text-slate-200 font-medium truncate"
                              title={dev.alias ? `${dev.alias} (${dev.name})` : dev.name}
                            >
                              {displayName(dev)}
                            </div>
                            <div className="text-[9px] text-slate-600 font-mono flex gap-1 items-center">
                              {!dev.isFactory && (
                                <span className="truncate">{dev.id}</span>
                              )}
                              {dev.isFactory && (
                                <span className="italic">Template</span>
                              )}
                            </div>
                            {dev.deviceAnchor === 'ephemeral' && !dev.isFactory && !dev.virtual && (
                              <div
                                className="text-[8px] text-amber-500/80 truncate"
                                title="This device has no persistent identifier. After a restart, it will register as a new device and must be approved again."
                              >
                                ephemeral identifier
                              </div>
                            )}
                            {dev.clientIp && (
                              <div
                                className="text-[8px] text-slate-600 font-mono truncate"
                                title={dev.clientIp}
                              >
                                {dev.clientIp}
                              </div>
                            )}
                          </div>
                        </div>
                        <div className="flex items-center gap-1.5 opacity-0 group-hover:opacity-100 transition-opacity">
                          {!dev.isFactory && (
                            <button
                              type="button"
                              onClick={(e) => {
                                e.stopPropagation();
                                // Credentials are held per device, not per provider.
                                const targetId = dev.deviceId || dev.providerId || dev.id;
                                if (window.confirm(`Do you really want to revoke device '${displayName(dev)}' (${targetId})?`)) {
                                  onRevokeDevice?.(targetId);
                                }
                              }}
                              className="p-1 rounded text-slate-500 hover:text-rose-400 hover:bg-slate-800 transition-colors"
                              title="Revoke device"
                            >
                              <Icons.Trash2 size={12} />
                            </button>
                          )}
                          <Icons.Move
                            size={12}
                            className="text-slate-600 cursor-grab active:cursor-grabbing"
                          />
                        </div>
                      </div>
                    );
                  })}
                  {items.length === 0 && (
                    <div className="text-[10px] text-slate-600 italic px-2">
                      No devices
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })}

        {treeGrouping === "device" && [...deviceGroups.values()].map((device) => {
          const deviceKey = `device:${device.id}`;
          const deviceExpanded = expanded[deviceKey] ?? true;
          const providerCount = device.providers.size;

          return (
            <div key={device.id}>
              <button
                type="button"
                className="w-full flex items-center gap-2 text-slate-400 text-xs font-bold uppercase tracking-widest cursor-pointer hover:text-slate-200 mb-2"
                aria-expanded={deviceExpanded}
                aria-controls={`elab-devicetree-section-${device.id}`}
                onClick={() => setExpanded((previous) => ({ ...previous, [deviceKey]: !deviceExpanded }))}
              >
                {deviceExpanded ? <Icons.ChevronDown size={12} /> : <Icons.ChevronRight size={12} />}
                <Icons.Server size={12} className="text-sky-500" />
                <span className="truncate" title={device.name}>{device.name}</span> ({providerCount})
              </button>

              {deviceExpanded && (
                <div
                  id={`elab-devicetree-section-${device.id}`}
                  className="space-y-2 pl-2 border-l border-slate-800 ml-1.5"
                >
                  {[...device.providers.values()].map((provider) => (
                    <div key={provider.id}>
                      <div className="flex items-center gap-1.5 text-[9px] text-slate-500 font-mono px-2 mb-1">
                        <Icons.Cpu size={11} />
                        <span className="truncate" title={provider.id}>{provider.id}</span>
                      </div>
                      <div className="space-y-1 pl-2">
                        {provider.tasks.map((dev) => {
                          const { icon: TypeIcon, color } = getTypeInfo(dev.type);
                          return (
                            <div
                              key={dev.id}
                              draggable
                              onDragStart={(e) => handleDragStart(e, dev)}
                              onTouchStart={(e) => handleTouchStart(e, dev)}
                              onTouchMove={handleTouchMove}
                              onTouchEnd={handleTouchEnd}
                              onTouchCancel={handleTouchCancel}
                              className="group flex items-center justify-between p-2 rounded bg-slate-900 border border-transparent hover:border-slate-700 cursor-grab active:cursor-grabbing hover:shadow-md transition-all"
                            >
                              <div className="flex items-center gap-2 overflow-hidden">
                                <TypeIcon size={14} className={color} />
                                <div className="overflow-hidden min-w-0">
                                  <div
                                    className="text-xs text-slate-200 font-medium truncate"
                                    title={dev.alias ? `${dev.alias} (${dev.name})` : dev.name}
                                  >
                                    {displayName(dev)}
                                  </div>
                                  <div className="text-[9px] text-slate-600 font-mono flex gap-1 items-center">
                                    {!dev.isFactory && <span className="truncate">{dev.id}</span>}
                                    {dev.isFactory && <span className="italic">Template</span>}
                                  </div>
                                  {dev.deviceAnchor === 'ephemeral' && !dev.isFactory && !dev.virtual && (
                                    <div
                                      className="text-[8px] text-amber-500/80 truncate"
                                      title="This device has no persistent identifier. After a restart, it will register as a new device and must be approved again."
                                    >
                                      ephemeral identifier
                                    </div>
                                  )}
                                  {dev.clientIp && <div className="text-[8px] text-slate-600 font-mono truncate" title={dev.clientIp}>{dev.clientIp}</div>}
                                </div>
                              </div>
                              <div className="flex items-center gap-1.5 opacity-0 group-hover:opacity-100 transition-opacity">
                                {!dev.isFactory && (
                                  <button
                                    type="button"
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      const targetId = dev.deviceId || dev.providerId || dev.id;
                                      if (window.confirm(`Do you really want to revoke device '${displayName(dev)}' (${targetId})?`)) {
                                        onRevokeDevice?.(targetId);
                                      }
                                    }}
                                    className="p-1 rounded text-slate-500 hover:text-rose-400 hover:bg-slate-800 transition-colors"
                                    title="Revoke device"
                                  >
                                    <Icons.Trash2 size={12} />
                                  </button>
                                )}
                                <Icons.Move size={12} className="text-slate-600 cursor-grab active:cursor-grabbing" />
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          );
        })}

        {/* LIBRARY SECTION */}
        <div>
          <button
            type="button"
            className="w-full flex items-center gap-2 text-slate-400 text-xs font-bold uppercase tracking-widest cursor-pointer hover:text-slate-200 mb-2"
            aria-expanded={!!expanded["Library"]}
            aria-controls="elab-devicetree-section-library"
            onClick={() =>
              setExpanded((p) => ({ ...p, Library: !p["Library"] }))
            }
          >
            {expanded["Library"] ? (
              <Icons.ChevronDown size={12} />
            ) : (
              <Icons.ChevronRight size={12} />
            )}
            Library ({scripts.length})
          </button>
          {expanded["Library"] && (
            <div
              id="elab-devicetree-section-library"
              className="space-y-1 pl-2 border-l border-slate-800 ml-1.5"
            >
              {scripts.map((script) => (
                <div
                  key={script.name}
                  onClick={() =>
                    !script.isRunning && onStartScript(script.filename)
                  }
                  className={`relative group flex items-center justify-between p-2 rounded border border-transparent transition-all cursor-pointer hover:border-slate-700 hover:shadow-md ${
                    script.isRunning
                      ? "bg-slate-800/80 border-slate-700"
                      : "bg-slate-900"
                  }`}
                >
                  <div className="flex items-center gap-2">
                    <Icons.FileCode
                      size={14}
                      className={
                        script.isRunning
                          ? "text-green-500 animate-pulse"
                          : "text-slate-500"
                      }
                    />
                    <div>
                      <div
                        className={`text-xs font-medium ${script.isRunning ? "text-green-400" : "text-slate-400"}`}
                      >
                        {script.name}
                      </div>
                      <div className="text-[9px] text-slate-600 font-mono">
                        {script.isRunning ? "RUNNING" : "SCRIPT"}
                      </div>
                    </div>
                  </div>
                  {script.isRunning ? (
                    <button
                      className="mx-1 rounded bg-slate-900 text-red-500 hover:bg-red-900/50 hover:text-red-300 border border-transparent hover:border-red-500/50 z-10"
                      onClick={(e) => {
                        e.stopPropagation();
                        onStopScript(script.filename);
                      }}
                    >
                      <Icons.Square size={10} fill="currentColor" />
                    </button>
                  ) : (
                    <Icons.Play
                      size={12}
                      className="text-slate-500 opacity-0 group-hover:opacity-100 transition-opacity mr-1"
                    />
                  )}
                </div>
              ))}
            </div>
          )}
        </div>

        {/* REGISTRATION: pending devices awaiting operator approval (TOFU). */}
        {pendingDevices && pendingDevices.length > 0 && (
          <div className="border border-amber-700/60 rounded-lg bg-amber-950/30 p-2">
            <div className="flex items-center gap-2 mb-2">
              <Icons.ShieldAlert size={14} className="text-amber-400" />
              <h3 className="text-xs font-bold uppercase tracking-wider text-amber-300">
                Registration
              </h3>
              <span className="ml-auto text-[9px] font-mono bg-amber-900/60 text-amber-200 px-1.5 py-0.5 rounded">
                {pendingDevices.length} pending
              </span>
            </div>
            <p className="text-[10px] text-amber-200/70 mb-2 leading-snug">
              New devices must be approved once. Afterwards, they will
              authenticate automatically.
            </p>
            <div className="space-y-2">
              {pendingDevices.map((dev) => {
                const deviceId = dev?.deviceId ?? dev?.device_id ?? dev?.id;
                const name = dev?.manifest?.name || deviceId || "Unknown";
                const ip = dev?.clientIp || dev?.client_ip || "?";
                const hash = dev?.manifestHash || dev?.manifest_hash || "";
                const hashShort = hash ? hash.slice(0, 8) : "—";
                const device = dev?.manifest?.device || {};
                const anchor = device.anchor || "ephemeral";
                return (
                  <div
                    key={deviceId}
                    className="p-2 bg-slate-900 border border-slate-800 rounded"
                  >
                    <div className="flex items-start justify-between gap-2 mb-1">
                      <div className="min-w-0 flex-1">
                        <div className="text-xs font-medium text-slate-200 truncate">
                          {name}
                        </div>
                        <div className="text-[9px] text-slate-500 font-mono truncate">
                          {deviceId}
                        </div>
                      </div>
                    </div>
                    <div className="flex items-center gap-2 text-[9px] text-slate-500 font-mono mb-1">
                      <span>{ip}</span>
                      <span>·</span>
                      <span title={hash}>hash:{hashShort}</span>
                      {device.model && (
                        <>
                          <span>·</span>
                          <span title="Device model (firmware)">{device.model}</span>
                        </>
                      )}
                    </div>
                    {anchor === "ephemeral" && (
                      <div className="text-[9px] text-amber-400/90 mb-2 leading-snug">
                        No persistent identifier — registers as a new device
                        after restart and must be approved again.
                      </div>
                    )}
                    {anchor !== "ephemeral" && (
                      <div className="text-[9px] text-slate-600 font-mono mb-2">
                        Identifier: {anchor}
                      </div>
                    )}
                    <div className="flex gap-1.5">
                      <button
                        onClick={() => onApproveDevice?.(deviceId, hash)}
                        className="flex-1 px-2 py-1 text-[10px] font-bold rounded bg-emerald-700 hover:bg-emerald-600 text-white transition"
                        title="Approve device and issue key"
                      >
                        Approve
                      </button>
                      <button
                        onClick={() => onRevokeDevice?.(deviceId)}
                        className="flex-1 px-2 py-1 text-[10px] font-bold rounded bg-slate-800 hover:bg-rose-900/60 text-slate-300 hover:text-rose-200 border border-slate-700 transition"
                        title="Disconnect and reject key"
                      >
                        Reject
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </div>
    );
  },
);

DeviceTree.displayName = "DeviceTree";
