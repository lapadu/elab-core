import React, { useState, memo } from "react";
import { Icons } from "../utils/Shared";

const generateInstanceId = () => `inst_${Date.now()}`;

const STORAGE_KEY_TREE_EXPANDED = "elab.v1.tree_expanded";
const STORAGE_KEY_CATEGORY_FILTER = "elab.v1.category_filter";
const STORAGE_KEY_TAG_FILTERS = "elab.v1.tag_filters";

const loadExpandedState = () => {
  try {
    const saved = localStorage.getItem(STORAGE_KEY_TREE_EXPANDED);
    return saved
      ? JSON.parse(saved)
      : {
          Sensoren: true,
          Aktoren: true,
          Generatoren: true,
          Math: true,
          Measures: true,
          Recorded: true,
          Triggers: true,
          Library: true,
        };
  } catch (error) {
    console.error("Failed to load expanded state:", error);
    return {
      Sensoren: true,
      Aktoren: true,
      Generatoren: true,
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
 *  onStopScript: (filename: string) => void
 * }} props
 */
export const DeviceTree = memo(
  ({ devices, scripts = [], onStartScript, onStopScript }) => {
    const [expanded, setExpandedLocal] = useState(() => loadExpandedState());
    const [categoryFilter, setCategoryFilterLocal] = useState(() => {
      try {
        return localStorage.getItem(STORAGE_KEY_CATEGORY_FILTER) || null;
      } catch (error) {
        console.warn("Failed to load category filter:", error);
        return null;
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

    const setCategoryFilter = (value) => {
      setCategoryFilterLocal(value);
      try {
        localStorage.setItem(STORAGE_KEY_CATEGORY_FILTER, value || '');
      } catch (error) {
        console.warn("Failed to save category filter:", error);
      }
      // Reset tag filters when category changes
      setTagFiltersLocal(new Set());
      try {
        localStorage.setItem(STORAGE_KEY_TAG_FILTERS, '[]');
      } catch (error) {
        console.warn("Failed to reset tag filters:", error);
      }
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

    const setExpanded = (updater) => {
      setExpandedLocal((prev) => {
        const next = typeof updater === "function" ? updater(prev) : updater;
        saveExpandedState(next);
        return next;
      });
    };

    const getExpandedState = () => {
      const values = Object.values(expanded);
      const allExpanded = values.every((v) => v === true);
      const allCollapsed = values.every((v) => v === false);

      if (allExpanded) return "expanded";
      if (allCollapsed) return "collapsed";
      return "mixed";
    };

    const handleToggleExpandAll = () => {
      const state = getExpandedState();
      if (state === "expanded") {
        // All are expanded, so collapse all
        const allCollapsed = Object.keys(expanded).reduce((acc, key) => {
          acc[key] = false;
          return acc;
        }, {});
        setExpanded(allCollapsed);
      } else {
        // All are collapsed or mixed, so expand all
        const allExpanded = Object.keys(expanded).reduce((acc, key) => {
          acc[key] = true;
          return acc;
        }, {});
        setExpanded(allExpanded);
      }
    };

    const getTypeInfo = (type) => {
      const t = (type || "").toUpperCase();
      switch (t) {
        case "ACTUATOR":
          return {
            icon: Icons.Zap,
            color: "text-blue-500",
            filterKey: "ACTUATOR",
            label: "Actor",
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

    const filterByCategory = (items) => {
      if (!categoryFilter) return items;
      return items.filter((dev) => {
        if (categoryFilter === 'HARDWARE') return !dev.virtual;
        if (categoryFilter === 'VIRTUAL') return dev.virtual;
        return true;
      });
    };

    const filterByTags = (items) => {
      if (tagFilters.size === 0) return items;
      return items.filter((dev) => {
        const devTags = dev.tags || [];
        return [...tagFilters].every((tag) => devTags.includes(tag));
      });
    };

    const filterList = (items) => {
      return filterByTags(filterByCategory(items));
    };

    /** Collect all unique tags from items visible after L1 category filter. */
    const collectVisibleTags = () => {
      const tags = new Set();
      Object.values(devices).forEach((items) => {
        filterByCategory(items).forEach((dev) => {
          (dev.tags || []).forEach((t) => tags.add(t));
        });
      });
      return [...tags].sort();
    };

    const visibleTags = collectVisibleTags();

    /**
     * @param {React.DragEvent} e
     * @param {import('../plugins/core/ManifestTypes').Task} dev
     */
    const handleDragStart = (e, dev) => {
      try {
        const taskData = dev.isFactory ? dev.createTask() : dev;

        // Keep the drag payload limited to the data needed by the reducer.
        const cleanPayload = {
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

        const jsonStr = JSON.stringify(cleanPayload);
        e.dataTransfer.setData("task", jsonStr);
        e.dataTransfer.effectAllowed = "copy";
      } catch (error) {
        console.error("Error in drag start:", error);
        e.preventDefault();
      }
    };

    const categoryButtons = [
      { id: null, icon: Icons.Layers, label: "Alle" },
      { id: "HARDWARE", icon: Icons.Zap, label: "Hardware" },
      { id: "VIRTUAL", icon: Icons.Cpu, label: "Virtuell" },
    ];

    const expandedState = getExpandedState();
    const isExpanded = expandedState === "expanded";

    return (
      <div className="p-4 space-y-4">
        {/* FILTER & EXPAND BUTTONS */}
        <div className="flex items-center mb-4 bg-slate-900 p-1 rounded-lg border border-slate-800">
          <button
            onClick={handleToggleExpandAll}
            className="p-1 rounded transition-all flex items-center gap-1 text-slate-500 hover:text-slate-300 hover:bg-slate-800 shrink-0"
            title={isExpanded ? "Collapse all" : "Expand all"}
          >
            {isExpanded ? (
              <Icons.ListCollapse size={12} />
            ) : (
              <Icons.ListChevronsUpDown size={12} />
            )}
          </button>
          <div className="w-px h-6 bg-slate-700 mx-2 shrink-0"></div>
          <div className="flex-1 flex justify-center gap-1 flex-wrap">
            {categoryButtons.map((f) => (
              <button
                key={f.id ?? "ALL"}
                onClick={() => setCategoryFilter(f.id)}
                className={`p-1 rounded transition-all flex items-center gap-1 ${
                  categoryFilter === f.id
                    ? "bg-slate-700 text-white shadow-sm"
                    : "text-slate-500 hover:text-slate-300 hover:bg-slate-800"
                }`}
                title={`Filter ${f.label}`}
              >
                <f.icon size={12} />
                <span className="text-[7px] font-bold uppercase hidden sm:inline">
                  {f.label}
                </span>
              </button>
            ))}
          </div>
        </div>

        {/* TAG FILTER (Level 2) */}
        {visibleTags.length > 0 && (
          <div className="flex flex-wrap gap-1 mb-2">
            {visibleTags.map((tag) => (
              <button
                key={tag}
                onClick={() => toggleTagFilter(tag)}
                className={`px-1.5 py-0.5 rounded text-[8px] font-medium transition-all border ${
                  tagFilters.has(tag)
                    ? "bg-sky-900/60 text-sky-300 border-sky-700"
                    : "bg-slate-900 text-slate-500 border-slate-800 hover:text-slate-300 hover:border-slate-700"
                }`}
              >
                {tag}
              </button>
            ))}
          </div>
        )}

        {/* DEVICE LISTS */}
        {Object.entries(devices).map(([category, rawItems]) => {
          const items = filterList(rawItems);

          if (
            items.length === 0 &&
            rawItems.length > 0 &&
            (categoryFilter || tagFilters.size > 0)
          )
            return null;

          return (
            <div key={category}>
              <div
                className="flex items-center gap-2 text-slate-400 text-xs font-bold uppercase tracking-widest cursor-pointer hover:text-slate-200 mb-2"
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
              </div>

              {expanded[category] && (
                <div className="space-y-1 pl-2 border-l border-slate-800 ml-1.5">
                  {items.map((dev) => {
                    const { icon: TypeIcon, color } = getTypeInfo(dev.type);
                    return (
                      <div
                        key={dev.id}
                        draggable
                        onDragStart={(e) => handleDragStart(e, dev)}
                        className="group flex items-center justify-between p-2 rounded bg-slate-900 border border-transparent hover:border-slate-700 cursor-grab active:cursor-grabbing hover:shadow-md transition-all"
                      >
                        <div className="flex items-center gap-2 overflow-hidden">
                          <TypeIcon size={14} className={color} />
                          <div className="overflow-hidden min-w-0">
                            <div
                              className="text-xs text-slate-200 font-medium truncate"
                              title={dev.name}
                            >
                              {dev.name}
                            </div>
                            <div className="text-[9px] text-slate-600 font-mono flex gap-1 items-center">
                              {!dev.isFactory && (
                                <span className="truncate">{dev.id}</span>
                              )}
                              {dev.isFactory && (
                                <span className="italic">Template</span>
                              )}
                            </div>
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
                        <Icons.Move
                          size={12}
                          className="text-slate-600 opacity-0 group-hover:opacity-100 transition-opacity"
                        />
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

        {/* LIBRARY SECTION */}
        <div>
          <div
            className="flex items-center gap-2 text-slate-400 text-xs font-bold uppercase tracking-widest cursor-pointer hover:text-slate-200 mb-2"
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
          </div>
          {expanded["Library"] && (
            <div className="space-y-1 pl-2 border-l border-slate-800 ml-1.5">
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
      </div>
    );
  },
);

DeviceTree.displayName = "DeviceTree";
