import React, { useState, useMemo, useReducer, useEffect, useRef, useCallback } from 'react';
import { Icons, COLOR_PALETTE } from './utils/Shared.jsx';
import dispatcher from './services/DispatcherClient.js';
import { DeviceTree } from './components/DeviceTree.jsx';
import { WidgetHost } from './components/WidgetHost.jsx';
import { PLUGIN_REGISTRY } from './components/PluginRegistry.jsx';
import { useDispatcherSubscription } from './hooks/useDispatcherSubscription.js';
import { slotReducer, initialSlotState, createTaskInstanceCache } from './reducers/slotReducer.js';
import { APP_EVENTS } from './utils/EventTypes.js';
import { RecordedTaskPlugin } from './plugins/core/RecordedTask.jsx';
import { SineGenClientPlugin, SinusGenTemplate } from './plugins/SinusGenerator.jsx';
import { SessionRecorder } from './components/SessionRecorder.jsx';
import { SidebarHeader } from './components/SidebarHeader.jsx';
import { Workspace } from './components/Workspace.jsx';
import { LayoutSwitcher } from './components/LayoutSwitcher.jsx';
import { LayoutSettings } from './components/LayoutSettings.jsx';
import { HelpPlugin } from './plugins/Help/index.jsx';
import { DispatchFlowPlugin } from './plugins/DispatchFlow/index.jsx';
import { mapProviderTaskToAvailableDevice } from './utils/mapProviderTaskToAvailableDevice.js';

function remapTaskReference(savedObj, templateSlots, loadedSlots) {
  if (!savedObj || typeof savedObj !== 'object') return savedObj;

  if (Array.isArray(savedObj)) {
    return savedObj.map(item => remapTaskReference(item, templateSlots, loadedSlots));
  }

  // If this looks like a task reference (has id and groupId), find its loaded version.
  if (savedObj.id && savedObj.groupId && savedObj.originalId) {
    for (const [slotIdx, loadedTask] of Object.entries(loadedSlots)) {
      if (!loadedTask) continue;
      const savedSlot = templateSlots[slotIdx];
      if (savedSlot && (savedSlot.id === savedObj.id || savedSlot.originalId === savedObj.originalId)) {
        return loadedTask;
      }
    }
  }

  const remapped = {};
  for (const [key, value] of Object.entries(savedObj)) {
    remapped[key] = remapTaskReference(value, templateSlots, loadedSlots);
  }
  return remapped;
}

const SERVER_URL = `http://${window.location.hostname}:5000`;

// Manually register the core plugin for recorded tasks
PLUGIN_REGISTRY[RecordedTaskPlugin.id] = RecordedTaskPlugin;
PLUGIN_REGISTRY[SineGenClientPlugin.id] = SineGenClientPlugin;
PLUGIN_REGISTRY[SinusGenTemplate.id] = SinusGenTemplate;

export default function App() {
  const { 
    isConnected, 
    sessionState, 
    streamBuffers, 
    providers, 
    offlineProviders,
    availableScripts,
    startScript,
    stopScript,
    clearStreamBuffers,
  } = useDispatcherSubscription(SERVER_URL);

  const [slots, _rawDispatchSlots] = useReducer(slotReducer, initialSlotState);
  // Per-App task instance cache. Held in a ref so it survives renders without
  // becoming module-level shared state (which broke isolation in tests and
  // would block ever rendering two App instances side-by-side).
  const taskCacheRef = useRef(createTaskInstanceCache());
  const dispatchSlots = useCallback(
    (action) => _rawDispatchSlots({ ...action, cache: taskCacheRef.current }),
    [],
  );
  const slotsRef = useRef(slots);
  useEffect(() => {
    slotsRef.current = slots;
  }, [slots]);

  // Snapshot delivered by the server right after register_client. Held until
  // the providers list arrives so we can resolve task ids to instances.
  const pendingSnapshotRef = useRef(null);
  const providersRef = useRef(providers);

  const [layout, setLayout] = useState('grid-2x2');
  const [isHelpOpen, setIsHelpOpen] = useState(false);
  const [isFlowOpen, setIsFlowOpen] = useState(false);
  
  // --- SESSION/REPLAY STATE MANAGEMENT ---
  const [sessionName, setSessionName] = useState('');
  const [sessions, setSessions] = useState([]);
  const [selectedSession, setSelectedSession] = useState('');
  const [isReplayMode, setIsReplayMode] = useState(false);
  const [isSessionLoaded, setIsSessionLoaded] = useState(false);
  const [recordedTasks, setRecordedTasks] = useState([]);
  
    const [replayState, setReplayState] = useState({ state: 'stopped', time: 0, duration: 1 });
    const [seekValue, setSeekValue] = useState(0);
    const seekThrottle = useRef(null);
  
    // --- HANDLER FUNCTIONS ---
  
    const handleRecordToggle = () => {
      if (sessionState.recording) {
          dispatcher.stopSession();
      } else {
          const name = (sessionName || '').trim();
          dispatcher.startSession(name);
      }
    };
  
    const handleUnloadSession = () => {
      dispatcher.sendReplayAction('unload'); // Tell server to release session
      setIsSessionLoaded(false);
      setIsReplayMode(false);
      setRecordedTasks([]);
      setReplayState({ state: 'stopped', time: 0, duration: 1 });
      setSeekValue(0);
      clearStreamBuffers(); // Flush all buffers on unload
    }
  
    const handleLoadSession = () => {
      if (isSessionLoaded) {
        handleUnloadSession();
      } else {
        if (selectedSession) {
          if (sessionState.recording) dispatcher.stopSession();
          dispatcher.loadSession(selectedSession);
        }
      }
    };
  
    const handleDeleteSession = () => {
      if (selectedSession) {
          const isConfirmed = window.confirm(`Are you sure you want to delete the session "${selectedSession}"?\nThis cannot be undone.`);
          if (isConfirmed) {
              dispatcher.deleteSession(selectedSession);
          }
      }
    };
  
    // --- EFFECT HOOKS for dispatcher events ---
    useEffect(() => {
      dispatcher.getSessions();

      const handleReplayControl = (action, value = null) => {
        if (action === 'stop') {
          setReplayState(prev => ({ ...prev, state: 'paused' }));
          setSeekValue(0);
          dispatcher.sendReplayAction('seek', 0); // Seek to beginning
          dispatcher.sendReplayAction('pause');
        } else {
          // Beim Seek-Befehl die Buffer der aufgezeichneten Tasks leeren
          if (action === 'seek') {
            const taskIds = recordedTasks.flatMap(p => (p.tasks || []).map(t => t.id));
            clearStreamBuffers(taskIds);
          }
          dispatcher.sendReplayAction(action, value);
        }
      };
  
      const handleSessionList = (list) => {
          setSessions(list || []);
          // Preserve selected session if it still exists in the new list
          if (!list?.includes(selectedSession) && list?.length > 0) {
              setSelectedSession(list[0]);
          }
      };
      const handleRecordedProviders = (data) => {
        setRecordedTasks(data.providers || []);
      }
      
      const handleReplayLoaded = (data) => {
          if (data.success) {
              setIsSessionLoaded(true);
              setIsReplayMode(true);
              setRecordedTasks([]); // Clear old tasks
              dispatcher.getRecordedProviders(data.session_id);
              setReplayState({ state: 'paused', time: 0, duration: data.duration || 1 });
              setSeekValue(0);
          } else {
              console.error("Failed to load session:", data.message);
              setIsSessionLoaded(false);
          }
      };
  
      const handleSessionStatus = (status) => {
        // Refresh the session list after recording stops.
        if (!status.recording) {
          setTimeout(() => dispatcher.getSessions(), 500);
        }
      };
  
      const handleReplayStatus = (status) => {
          setReplayState(prev => ({ ...prev, state: status.state }));
      };
      
      const handleReplayProgress = (progress) => {
          const time = progress.time_ms || 0;
          const duration = progress.duration || replayState.duration || 1;
          
          // Auto-stop at the end
          if (time >= duration) {
              handleReplayControl('stop');
          }
  
          // Prevent the slider from jumping while the user is dragging it.
          if (!document.querySelector('input[type=range]:active')) {
              setReplayState(prev => ({ ...prev, time, duration }));
              setSeekValue(time);
          }
      };
  
      dispatcher.on(APP_EVENTS.ON_SESSION_LIST, handleSessionList);
      dispatcher.on(APP_EVENTS.ON_SESSION_STATUS, handleSessionStatus);
      dispatcher.on(APP_EVENTS.ON_RECORDED_PROVIDERS, handleRecordedProviders);
      dispatcher.on(APP_EVENTS.ON_REPLAY_LOADED, handleReplayLoaded);
      dispatcher.on(APP_EVENTS.ON_REPLAY_STATUS, handleReplayStatus);
      dispatcher.on(APP_EVENTS.ON_REPLAY_PROGRESS, handleReplayProgress);
      
      const handleProviderMetaChanged = (data) => {
        const { task_id, changes } = data;
        if (!task_id || !changes) return;

        Object.entries(slots).forEach(([index, slot]) => {
            if (slot?.id === task_id) {
                const updatedTask = { ...slot, ...changes };
                if (changes.config) {
                    updatedTask.config = { ...slot.config, ...changes.config };
                }
                dispatchSlots({ type: 'UPDATE_TASK', index, task: updatedTask });
            }
        });
      };

      dispatcher.on(APP_EVENTS.ON_PROVIDER_META_CHANGED, handleProviderMetaChanged);

      const handleTaskRejected = (data) => {
        const { slot, taskId, reason } = data;
        console.warn(`⛔ Task ${taskId} rejected for slot ${slot}: ${reason}`);
        if (slot !== undefined && slot !== null) {
          dispatchSlots({ type: 'REMOVE_TASK', index: slot });
        }
      };
      dispatcher.on(APP_EVENTS.ON_TASK_REJECTED, handleTaskRejected);

      const handleActiveTasksSnapshot = (data) => {
        // Server tells us which slots it still considers occupied. Buffer the
        // map and resolve it once the provider list is available (see effect
        // below). We never call assignTaskToSlot here - the server already
        // has these assignments registered.
        if (data?.slots && typeof data.slots === 'object') {
          pendingSnapshotRef.current = data.slots;
          console.log('📥 Received active_tasks_snapshot:', data.slots);
          // Try to resolve immediately in case providers are already loaded.
          if (providersRef.current.length > 0) {
            dispatchSlots({
              type: 'RESTORE_SNAPSHOT',
              slotMap: pendingSnapshotRef.current,
              providers: providersRef.current,
            });
            pendingSnapshotRef.current = null;
          }
        }
      };
      dispatcher.on(APP_EVENTS.ON_ACTIVE_TASKS_SNAPSHOT, handleActiveTasksSnapshot);

      return () => {
          dispatcher.off(APP_EVENTS.ON_SESSION_LIST, handleSessionList);
          dispatcher.off(APP_EVENTS.ON_SESSION_STATUS, handleSessionStatus);
          dispatcher.off(APP_EVENTS.ON_RECORDED_PROVIDERS, handleRecordedProviders);
          dispatcher.off(APP_EVENTS.ON_REPLAY_LOADED, handleReplayLoaded);
          dispatcher.off(APP_EVENTS.ON_REPLAY_STATUS, handleReplayStatus);
          dispatcher.off(APP_EVENTS.ON_REPLAY_PROGRESS, handleReplayProgress);
          dispatcher.off(APP_EVENTS.ON_PROVIDER_META_CHANGED, handleProviderMetaChanged);
          dispatcher.off(APP_EVENTS.ON_TASK_REJECTED, handleTaskRejected);
          dispatcher.off(APP_EVENTS.ON_ACTIVE_TASKS_SNAPSHOT, handleActiveTasksSnapshot);
      };
    }, [selectedSession, replayState.duration, recordedTasks, slots, clearStreamBuffers, dispatchSlots]);

    // When providers change, rebind orphaned slot tasks to reconnected providers
    // and replay a deferred snapshot if one is pending.
    useEffect(() => {
      providersRef.current = providers;
      if (providers.length > 0) {
        dispatchSlots({ type: 'REBIND_PROVIDER', providers });
        if (pendingSnapshotRef.current) {
          dispatchSlots({
            type: 'RESTORE_SNAPSHOT',
            slotMap: pendingSnapshotRef.current,
            providers,
          });
          pendingSnapshotRef.current = null;
        }
      }
    }, [providers, dispatchSlots]);
    
    const handleReplayControl = (action, value = null) => {
        if (action === 'stop') {
          setReplayState(prev => ({ ...prev, state: 'paused' }));
          setSeekValue(0);
          dispatcher.sendReplayAction('seek', 0); // Seek to beginning
          dispatcher.sendReplayAction('pause');
        } else {
          // Clear recorded-task buffers before seeking.
          if (action === 'seek') {
            const taskIds = recordedTasks.flatMap(p => (p.tasks || []).map(t => t.id));
            clearStreamBuffers(taskIds);
          }
          dispatcher.sendReplayAction(action, value);
        }
    };
    
    const handleSeekChange = (e) => {
      const val = parseFloat(e.target.value);
      setSeekValue(val);

      // Throttle live scrubbing so seek traffic stays responsive.
      if (seekThrottle.current) {
          clearTimeout(seekThrottle.current);
      }
      seekThrottle.current = setTimeout(() => {
          handleReplayControl('seek', val);
      }, 50); // Lower throttling keeps scrubbing feeling responsive.
    };

    const handleSeekMouseUp = (e) => {
        // Ensure the final slider value is sent.
        if (seekThrottle.current) {
            clearTimeout(seekThrottle.current);
        }
        const val = parseFloat(e.target.value);
        handleReplayControl('seek', val);
    };
  
  
    const availableDevices = useMemo(() => {
      const sensorList = [];
      const actorList = [];
      const generatorList = [];
      const mathList = [];
      const measureList = [];
      const recordedList = [];
      const triggerList = [
          {
              id: 'trigger_rising',
              name: 'Rising Edge',
              type: 'TRIGGER',
              groupId: 'virtual',
              config: { mode: 'rising', level: 0 },
              symbol: 'arrow_up',
              virtual: true,
              ui: { mode: 'generic' }
          },
          {
              id: 'trigger_falling',
              name: 'Falling Edge',
              type: 'TRIGGER',
              groupId: 'virtual',
              config: { mode: 'falling', level: 0 },
              symbol: 'arrow_down',
              virtual: true,
              ui: { mode: 'generic' }
          },
          {
              id: 'trigger_level',
              name: 'Level Match',
              type: 'TRIGGER',
              groupId: 'virtual',
              config: { mode: 'level', level: 0 },
              symbol: 'line',
              virtual: true,
              ui: { mode: 'generic' }
          }
      ];

      const sortDevice = (dev) => {
          if (dev.is_recorded) recordedList.push(dev);
          else {
              const type = (dev.type || 'SENSOR').toUpperCase();
              if (type === 'SENSOR') sensorList.push(dev);
              else if (type === 'ACTUATOR' || type === 'CONTROL') actorList.push(dev);
              else if (type === 'GENERATOR') generatorList.push(dev);
              else if (type === 'MATH') mathList.push(dev);
              else if (type === 'MEASURE') measureList.push(dev);
              else sensorList.push(dev);
          }
      };

      providers.forEach(p => {
          if (p.isUiInstance) return;
          const tasks = p.tasks?.length ? p.tasks : [p];
          tasks.forEach(t => {
            sortDevice(mapProviderTaskToAvailableDevice(p, t));
          });
      });
  
      Object.values(PLUGIN_REGISTRY).forEach(plugin => {
          if (typeof plugin.createTask !== 'function') return;
          const template = plugin.createTask();
          sortDevice({
              ...template,
              id: plugin.id,
              isFactory: true,
              createTask: plugin.createTask,
              type: template.type || 'SENSOR',
              virtual: template.virtual
          });
      });
      
      recordedTasks.forEach(p => {
        const tasks = p.tasks?.length ? p.tasks : [p];
        tasks.forEach(t => {
            const deviceId = t.id;
            const colorIndex = [...deviceId].reduce((acc, char) => acc + char.charCodeAt(0), 0) % COLOR_PALETTE.length;
            
            // Preserve the original task UI so the recorded widget looks like
            // its live counterpart. Fall back to the RecordedTask archive view
            // only when no template information is available.
            const origUi = t.ui || {};
            const recUi = origUi.template || origUi.views?.length
                ? { ...origUi }
                : { mode: 'generic', template: 'tpl_rec_default', defaultTemplate: 'tpl_rec_default' };

            sortDevice({
                id: deviceId,
                originalId: t.originalId,
                name: t.name,
                type: t.type,
                groupId: t.groupId || recUi.template || 'tpl_rec_default',
                providerId: p.id,
                color: t.color || COLOR_PALETTE[colorIndex],
                config: t.config || {},
                virtual: true,
                is_recorded: true,
                session_id: p.session_id,
                ui: recUi,
            });
        });
      });
  
  
      return { 'Sensoren': sensorList, 'Aktoren': actorList, 'Generatoren': generatorList, 'Math': mathList, 'Measures': measureList, 'Recorded': recordedList, 'Triggers': triggerList };
  }, [providers, recordedTasks]);

    const availableTaskMap = useMemo(() => {
      const entries = Object.values(availableDevices).flat();
      const map = new Map();

      entries.forEach(task => {
        const keys = [task.id, task.originalId, task.groupId].filter(Boolean);
        keys.forEach(key => {
          if (!map.has(key)) {
            map.set(key, task);
          }
        });
      });

      return map;
    }, [availableDevices]);
  
    const getLayoutConfig = () => {
      switch (layout) {
        case 'grid-2x2':
          return { slots: [0, 1, 2, 3], gridClass: 'grid grid-cols-2 grid-rows-2' };
        case 'grid-pro':
          return { slots: [0, 1, 2, 3, 4, 5], gridClass: 'grid grid-cols-3 grid-rows-2' };
        case 'grid-5x1':
          return { slots: [0, 1, 2, 3, 4, 5], gridClass: 'grid-5x1-layout' };
        default:
          return { slots: [0, 1, 2, 3], gridClass: 'grid grid-cols-2 grid-rows-2' };
      }
    };
    const { slots: activeSlots, gridClass } = getLayoutConfig();
  
    const handleDropOnSlot = useCallback((e, index) => {
      e.preventDefault();
      const dataStr = e.dataTransfer.getData('task');
      if (dataStr) {
        const task = JSON.parse(dataStr);
        dispatchSlots({ type: 'DROP_TASK', index, baseTask: task });
        dispatcher.assignTaskToSlot(index, task.id);
      }
    }, [dispatchSlots]);

    const handleRemoveTask = useCallback((index) => {
      const task = slotsRef.current[index];
      if (task) {
        dispatcher.unassignTaskFromSlot(index, task.id);
      }
      dispatchSlots({ type: 'REMOVE_TASK', index: index });
    }, [dispatchSlots]);

    const handleAddChannel = useCallback((targetSlotIndex, droppedTask) => {
      dispatchSlots({
          type: 'ADD_CHANNEL',
          index: targetSlotIndex,
          channelTask: droppedTask,
      });
    }, [dispatchSlots]);

    const handleUpdateTask = useCallback((index, updatedTask) => {
      dispatchSlots({ type: 'UPDATE_TASK', index, task: updatedTask });

      // Detect meta changes (color, name) and propagate to server
      const currentTask = slotsRef.current[index];
      if (currentTask) {
        const metaChanges = {};
        if (updatedTask.color && updatedTask.color !== currentTask.color) {
          metaChanges.color = updatedTask.color;
        }
        if (updatedTask.name && updatedTask.name !== currentTask.name) {
          metaChanges.name = updatedTask.name;
        }
        if (Object.keys(metaChanges).length > 0) {
          const providerId = `prov_${currentTask.originalId || currentTask.id}`;
          dispatcher.sendControlCommand(providerId, {
            action: 'update_meta',
            payload: metaChanges,
          });
        }
      }
    }, [dispatchSlots]);

    const handleLoadTemplate = useCallback((template) => {
      if (!template?.slots) {
        return { error: 'Invalid template data.' };
      }

      Object.entries(slotsRef.current).forEach(([slotIndex, slotTask]) => {
        if (slotTask) {
          dispatcher.unassignTaskFromSlot(Number(slotIndex), slotTask.id);
        }
      });

      dispatchSlots({ type: 'CLEAR_ALL' });

      if (template.layout) {
        setLayout(template.layout);
      }

      let loadedCount = 0;
      let missingCount = 0;
      const loadedSlots = {};

      // Phase 1: Load all tasks
      Object.entries(template.slots).forEach(([slotIndex, savedTask]) => {
        if (!savedTask) {
          loadedSlots[slotIndex] = null;
          return;
        }

        const matchedTask =
          availableTaskMap.get(savedTask.originalId) ||
          availableTaskMap.get(savedTask.id) ||
          availableTaskMap.get(savedTask.groupId);

        if (!matchedTask) {
          missingCount += 1;
          loadedSlots[slotIndex] = null;
          return;
        }

        const restoredExtraChannels = Array.isArray(savedTask.extraChannels)
          ? savedTask.extraChannels.filter(channel => {
              const matchedChannel =
                availableTaskMap.get(channel.originalId) ||
                availableTaskMap.get(channel.id);
              return !!matchedChannel;
            })
          : savedTask.extraChannels;

        const restoredTask = {
          ...matchedTask,
          ...savedTask,
          id: matchedTask.id,
          originalId: matchedTask.originalId || matchedTask.id,
          providerId: matchedTask.providerId,
          groupId: matchedTask.groupId,
          virtual: matchedTask.virtual,
          is_recorded: matchedTask.is_recorded,
          extraChannels: restoredExtraChannels,
        };

        loadedSlots[slotIndex] = restoredTask;
        dispatchSlots({ type: 'DROP_TASK', index: Number(slotIndex), baseTask: restoredTask });
        dispatcher.assignTaskToSlot(Number(slotIndex), restoredTask.id);
        loadedCount += 1;
      });

      // Phase 2: Remap all input connections
      Object.entries(loadedSlots).forEach(([slotIndex, loadedTask]) => {
        if (!loadedTask || !loadedTask.inputs) return;

        const remappedInputs = remapTaskReference(loadedTask.inputs, template.slots, loadedSlots);
        if (JSON.stringify(remappedInputs) !== JSON.stringify(loadedTask.inputs)) {
          const updatedTask = { ...loadedTask, inputs: remappedInputs };
          dispatchSlots({ type: 'UPDATE_TASK', index: Number(slotIndex), task: updatedTask });
        }
      });

      return { loadedCount, missingCount };
    }, [availableTaskMap, dispatchSlots]);

    return (
      <div className="flex h-screen bg-slate-950 text-slate-200 font-sans overflow-hidden select-none">
        
        <div className="w-64 flex flex-col border-r border-slate-800 bg-slate-950 z-20">
          <SidebarHeader isConnected={isConnected} />
  
          <div className="flex-1 overflow-y-auto custom-scrollbar">
              <DeviceTree 
                  devices={availableDevices} 
                  scripts={availableScripts}
                  onStartScript={startScript}
                  onStopScript={stopScript}
              />
          </div>
        </div>
  
        <div className="flex-1 flex flex-col relative">
          
          <div className="h-16 bg-slate-900 border-b border-slate-800 flex items-center px-4 gap-4">
            
            <SessionRecorder
              sessionState={sessionState}
              isReplayMode={isReplayMode}
              isSessionLoaded={isSessionLoaded}
              sessionName={sessionName}
              setSessionName={setSessionName}
              sessions={sessions}
              selectedSession={selectedSession}
              setSelectedSession={setSelectedSession}
              handleRecordToggle={handleRecordToggle}
              handleLoadSession={handleLoadSession}
              handleDeleteSession={handleDeleteSession}
              replayState={replayState}
              handleReplayControl={handleReplayControl}
              seekValue={seekValue}
              handleSeekChange={handleSeekChange}
              handleSeekMouseUp={handleSeekMouseUp}
            />

            <LayoutSettings slots={slots} layout={layout} onLoadTemplate={handleLoadTemplate} />
  
            <LayoutSwitcher layout={layout} setLayout={setLayout} />

            <div className="ml-auto" />

            <button
              type="button"
              onClick={() => setIsFlowOpen(true)}
              className="h-9 px-3 rounded-md bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-200 flex items-center gap-2 transition-colors"
              title="Dispatch Flow"
              aria-label="Dispatch Flow oeffnen"
            >
              <Icons.Activity size={14} />
              <span className="text-xs font-semibold uppercase tracking-wide">Flow</span>
            </button>

            <button
              type="button"
              onClick={() => setIsHelpOpen(true)}
              className="h-9 px-3 rounded-md bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-200 flex items-center gap-2 transition-colors"
              title="Hilfe"
              aria-label="Hilfe oeffnen"
            >
              <Icons.Info size={14} />
              <span className="text-xs font-semibold uppercase tracking-wide">Hilfe</span>
            </button>
          </div>

          {isFlowOpen && (
            <div className="absolute inset-0 z-[80] bg-slate-950/75 backdrop-blur-sm p-4 md:p-8">
              <div className="h-full w-full rounded-xl border border-slate-700 bg-slate-900 shadow-2xl flex flex-col overflow-hidden">
                <div className="h-12 px-4 border-b border-slate-800 flex items-center justify-between shrink-0">
                  <div className="flex items-center gap-2">
                    <Icons.Activity size={16} className="text-emerald-400" />
                    <h2 className="text-sm font-semibold text-slate-100">{DispatchFlowPlugin.label}</h2>
                  </div>
                  <button
                    type="button"
                    onClick={() => setIsFlowOpen(false)}
                    className="p-1.5 rounded hover:bg-slate-800 text-slate-300 hover:text-white transition-colors"
                    title="Schliessen"
                    aria-label="Dispatch Flow schliessen"
                  >
                    <Icons.X size={16} />
                  </button>
                </div>
                <div className="flex-1 overflow-auto p-4 md:p-6">
                  <DispatchFlowPlugin.render slots={slots} />
                </div>
              </div>
            </div>
          )}

          {isHelpOpen && (
            <div className="absolute inset-0 z-[80] bg-slate-950/75 backdrop-blur-sm p-4 md:p-8">
              <div className="h-full w-full rounded-xl border border-slate-700 bg-slate-900 shadow-2xl flex flex-col overflow-hidden">
                <div className="h-12 px-4 border-b border-slate-800 flex items-center justify-between shrink-0">
                  <div className="flex items-center gap-2">
                    <Icons.Info size={16} className="text-sky-400" />
                    <h2 className="text-sm font-semibold text-slate-100">{HelpPlugin.label}</h2>
                  </div>
                  <button
                    type="button"
                    onClick={() => setIsHelpOpen(false)}
                    className="p-1.5 rounded hover:bg-slate-800 text-slate-300 hover:text-white transition-colors"
                    title="Schliessen"
                    aria-label="Hilfe schliessen"
                  >
                    <Icons.X size={16} />
                  </button>
                </div>
                <div className="flex-1 overflow-auto p-4 md:p-6">
                  <HelpPlugin.render />
                </div>
              </div>
            </div>
          )}
  
          <Workspace
            gridClass={gridClass}
            activeSlots={activeSlots}
            slots={slots}
            offlineProviders={offlineProviders}
            providers={providers}
            handleDropOnSlot={handleDropOnSlot}
            handleUpdateTask={handleUpdateTask}
            handleRemoveTask={handleRemoveTask}
            handleAddChannel={handleAddChannel}
            streamBuffers={streamBuffers}
            dispatcherClient={dispatcher}
          />
  
        </div>
      </div>
    );
  }
  