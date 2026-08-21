import { factoryManager } from '../services/FactoryManager';
import { getPlugin } from '../components/PluginRegistry';

export const initialSlotState = { 0: null, 1: null, 2: null, 3: null, 4: null, 5: null };

/**
 * Fallback cache used when callers do not pass a `cache` Map in their action.
 * Provided so code paths outside the App can still dispatch to the reducer
 * without crashing. New code should pass an explicit cache (typically held in
 * a `useRef`) so multiple App instances or tests stay isolated.
 */
const _defaultTaskInstanceCache = new Map();

/**
 * Create a new task-instance cache. App instances should hold one of these in
 * a ref and pass it via `action.cache` so the reducer remains pure.
 */
export const createTaskInstanceCache = () => new Map();

/**
 * Stable identity of a task, used as instance-cache key and as a channel's
 * `originalId`.
 *
 * Live tasks are identified by their original id so the same source dropped
 * twice reuses one instance. Recorded tasks carry the live id in `originalId`,
 * so they must be identified by their own `rec_*` id — otherwise a recording
 * and its live source would collapse into one instance and the widget would
 * render live data instead of the recording.
 */
export const taskIdentity = (task) => {
    if (!task) return undefined;
    if (task.is_recorded) return task.id || task.originalId || task.groupId;
    return task.originalId || task.id || task.groupId;
};

export const slotReducer = (state, action) => {
    // Allow the caller to inject the cache so the reducer stays pure-ish; fall
    // back to a module-level Map for legacy call sites.
    const taskInstanceCache = action.cache instanceof Map
        ? action.cache
        : _defaultTaskInstanceCache;

    switch (action.type) {
        case 'DROP_TASK': {
            const { index, baseTask } = action;
            
            // Reuse the original task identity when available so drag-and-drop
            // does not create duplicate instances for the same source task.
            const cacheKey = taskIdentity(baseTask);
            
            let taskInstance;
            if (taskInstanceCache.has(cacheKey)) {
                // Reuse an existing instance.
                taskInstance = taskInstanceCache.get(cacheKey);
                console.log(`♻️ Reusing task instance: ${cacheKey}`);
            } else {
                // Create a new instance only on the first drop.
                taskInstance = {
                    ...baseTask,
                    originalId: baseTask.originalId || baseTask.id,
                    providerId: baseTask.providerId,
                    is_recorded: baseTask.is_recorded,
                    config: baseTask.config || {},
                    // Recorded tasks replay fixed data – no configurable source input.
                    inputs: (!baseTask.is_recorded && baseTask.type === 'SENSOR') ? { source: null } : undefined,
                    extraChannels: (baseTask.is_recorded || baseTask.groupId === 'system_csv_v1' || baseTask.groupId === 'logger') ? [] : null,
                };
                
                // Keep the instance in the shared cache.
                taskInstanceCache.set(cacheKey, taskInstance);
                console.log(`🆕 Created new task instance: ${cacheKey}`);
                
            }
            // Start the factory centrally when the task is virtual. Recorded
            // tasks are flagged virtual too, but they are fed by the replayer
            // only - starting the live factory would mix simulated data in.
            const plugin = getPlugin(baseTask.groupId);
            if (plugin && baseTask.virtual && !baseTask.is_recorded) {
                factoryManager.startFactory(baseTask, plugin);
            }
            
            return { ...state, [index]: taskInstance };
        }
        
        case 'UPDATE_TASK': {
            const { index, task } = action;
            
            // Refresh the cached instance using the original task identity when possible.
            const cacheKey = taskIdentity(task);
            if (taskInstanceCache.has(cacheKey)) {
                taskInstanceCache.set(cacheKey, task);
            }
            
            return { ...state, [index]: task };
        }
        
        case 'REMOVE_TASK': {
            const { index } = action;
            const task = state[index];
            
            // Only remove the cache entry when no slot still uses the task.
            const removedKey = taskIdentity(task);
            const isUsedElsewhere = Object.entries(state).some(
                ([slotIdx, slotTask]) => 
                    slotIdx !== String(index) && 
                    slotTask && taskIdentity(slotTask) === removedKey
            );
            
            if (!isUsedElsewhere && task) {
                taskInstanceCache.delete(removedKey);
                console.log(`🗑️ Removed task from cache: ${removedKey}`);
            }
            
            return { ...state, [index]: null };
        }
        
        case 'CLEAR_ALL': {
            taskInstanceCache.clear();
            return initialSlotState;
        }

        case 'RESTORE_SNAPSHOT': {
            // Server delivered the slot map it still considers active (e.g.
            // after a UI reload while another tab kept the dispatcher busy).
            // Build slot entries by resolving each task id against the current
            // provider list. Slots that cannot be resolved are left empty.
            const { slotMap, providers } = action;
            if (!slotMap || typeof slotMap !== 'object') return state;

            // Flat lookup: taskId -> { task, providerId } pulled from the
            // freshly received provider list.
            const taskIndex = new Map();
            for (const provider of providers || []) {
                if (!provider || provider.isUiInstance) continue;
                const tasks = provider.tasks?.length ? provider.tasks : [provider];
                for (const task of tasks) {
                    if (task?.id) {
                        taskIndex.set(task.id, { task, providerId: provider.id });
                    }
                }
            }

            const next = { ...state };
            let changed = false;
            for (const [slotIdxStr, taskId] of Object.entries(slotMap)) {
                const slotIdx = Number(slotIdxStr);
                if (next[slotIdx]) continue; // Don't clobber a slot the user already filled.
                const found = taskIndex.get(taskId);
                if (!found) continue;
                const { task, providerId } = found;

                const cacheKey = taskIdentity(task);
                let instance = taskInstanceCache.get(cacheKey);
                if (!instance) {
                    instance = {
                        ...task,
                        originalId: task.originalId || task.id,
                        providerId,
                        is_recorded: task.is_recorded,
                        config: task.config || {},
                        inputs: (!task.is_recorded && task.type === 'SENSOR') ? { source: null } : undefined,
                        extraChannels: (task.is_recorded || task.groupId === 'system_csv_v1' || task.groupId === 'logger') ? [] : null,
                    };
                    taskInstanceCache.set(cacheKey, instance);
                    console.log(`♻️ Restored task instance from server snapshot: ${cacheKey}`);
                }
                next[slotIdx] = instance;
                changed = true;
            }
            return changed ? next : state;
        }

        case 'REBIND_PROVIDER': {
            // When a provider reconnects with a new ID (e.g. FrequenceCounter restart),
            // update slot tasks that match by groupId to point to the new provider/task.
            const { providers } = action;
            let changed = false;
            const next = { ...state };
            for (const [idx, task] of Object.entries(next)) {
                if (!task || task.virtual || task.is_recorded) continue;
                // If the task's provider is already present, nothing to do
                if (providers.some(p => p.id === task.providerId)) continue;
                // Find a provider that has a task with the same groupId
                for (const p of providers) {
                    if (p.isUiInstance) continue;
                    const tasks = p.tasks?.length ? p.tasks : [p];
                    const match = tasks.find(t => t.groupId === task.groupId);
                    if (match) {
                        const cacheKey = taskIdentity(task);
                        const updated = {
                            ...task,
                            id: match.id,
                            originalId: match.id,
                            providerId: p.id,
                            name: match.name || task.name,
                            config: { ...task.config, ...match.config },
                        };
                        next[idx] = updated;
                        taskInstanceCache.set(cacheKey, updated);
                        changed = true;
                        break;
                    }
                }
            }
            return changed ? next : state;
        }
        
        case 'ADD_CHANNEL': {
            const { index, channelTask } = action;
            const targetTask = state[index];
            if (!targetTask) return state;
            
            const newChannel = {
                id: channelTask.id,
                originalId: taskIdentity(channelTask),
                name: channelTask.name,
                color: channelTask.color,
                config: channelTask.config || {}
            };
            
            const existingChannels = targetTask.extraChannels || [];
            if (existingChannels.find(c => c.id === newChannel.id)) return state;
            
            const updatedTask = {
                ...targetTask,
                extraChannels: [...existingChannels, newChannel]
            };
            
            // ✅ Cache aktualisieren
            const cacheKey = taskIdentity(updatedTask);
            taskInstanceCache.set(cacheKey, updatedTask);
            
            return { ...state, [index]: updatedTask };
        }
        
        default:
            return state;
    }
};