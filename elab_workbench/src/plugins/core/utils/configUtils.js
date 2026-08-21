/**
 * Helper: Config-Werte mit Fallbacks extrahieren
 */
export const getConfig = (task, channel = null) => {
  const config = channel?.config || task.config || {};
  return {
    factor: config.factor !== undefined ? config.factor : 1.0,
    unit: config.unit || config.siUnit || "",
    range: config.range || [-5, 5],
    min: config.min || 0,
    max: config.max || 100,
    step: config.step || 1,
  };
};

/**
 * Helper:Letzten Wert aus Buffer holen
 */
export const getLatestValue = (streamBuffers, taskId, originalId) => {
  const buffer = streamBuffers?.get(taskId) || streamBuffers?.get(originalId);
  if (!buffer) return null;

  const data = buffer.getData();
  return data.length > 0 ? data[data.length - 1].v : null;
};

/**
 * Helper: Generic channel list for any task/widget.
 *
 * A trigger is always bound to a channel, so channels are the common
 * denominator that makes the trigger model work across arbitrary providers
 * and widgets (not just the scope). Mirrors ScopeWidget's source resolution.
 */
export const getTaskChannels = (task) => {
  if (!task) return [];
  if (task.config?.singleSource) {
    return [{ id: task.originalId || task.id, name: task.name, color: task.color }];
  }
  const s = [];
  if (task.inputs?.source) s.push(task.inputs.source);
  if (Array.isArray(task.extraChannels)) s.push(...task.extraChannels);
  return Array.from(new Map(s.filter(Boolean).map((src) => [src.id, src])).values());
};

/**
 * Helper: Check if a task supports triggers.
 *
 * Generic rule: any widget/provider that exposes at least one channel can
 * receive triggers. Legacy/capability hints keep empty scope widgets eligible
 * before a channel is wired.
 */
export const taskSupportsTrigger = (task) => {
  if (!task) return false;
  if (getTaskChannels(task).length > 0) return true;
  if (task.type === 'MEASURE') return true;
  if (task.ui?.defaultTemplate === 'tpl_scope' || task.ui?.template === 'tpl_scope') return true;
  if (Array.isArray(task.capabilities) && task.capabilities.includes('trigger')) return true;
  if (task.config?.trigger !== undefined || task.config?.triggers !== undefined) return true;
  return false;
};

// --- Generic trigger model -------------------------------------------------
// task.config.triggers:        Array<{ id, channelId, mode, level, pretrigger }>
// task.config.activeTriggerId:  id of the trigger that aligns the scope time axis
//
// Any provider/widget can carry one trigger per channel (or several). A single
// "active" trigger drives the time-axis alignment; the rest are drawn as static
// level markers. The array shape keeps the door open for future composite
// triggers (an entry that references other trigger ids and is assigned to a
// channel of its own).

let _triggerSeq = 0;

/** Generate a stable, unique trigger id. */
export const makeTriggerId = () =>
  `trg_${Date.now().toString(36)}_${(_triggerSeq++).toString(36)}`;

/**
 * Normalized trigger array for a task, migrating the legacy single
 * `config.trigger` object into the array form on read.
 */
export const getTriggers = (task) => {
  const cfg = task?.config || {};
  if (Array.isArray(cfg.triggers)) return cfg.triggers;
  if (cfg.trigger) {
    return [{ id: cfg.trigger.id || 'trg_legacy', pretrigger: 5, ...cfg.trigger }];
  }
  return [];
};

/** The trigger that drives the time-axis alignment (or null). */
export const getActiveTrigger = (task) => {
  const triggers = getTriggers(task);
  if (triggers.length === 0) return null;
  const activeId = task?.config?.activeTriggerId;
  return triggers.find((t) => t.id === activeId) || triggers[0];
};

/**
 * Config patch that adds or replaces the trigger on a channel and makes it
 * active. Never mutates the input. Returns `{ triggers, activeTriggerId }`.
 */
export const upsertTriggerForChannel = (task, channelId, base = {}) => {
  const triggers = getTriggers(task).map((t) => ({ ...t }));
  const idx = triggers.findIndex((t) => t.channelId === channelId);
  if (idx >= 0) {
    triggers[idx] = { ...triggers[idx], ...base, channelId };
    return { triggers, activeTriggerId: triggers[idx].id };
  }
  const trigger = {
    id: makeTriggerId(),
    channelId: channelId ?? null,
    mode: base.mode || 'rising',
    level: base.level ?? 0,
    pretrigger: base.pretrigger ?? 5,
  };
  return { triggers: [...triggers, trigger], activeTriggerId: trigger.id };
};

/** Config patch that shallow-merges `patch` into a single trigger. */
export const patchTrigger = (task, triggerId, patch) => ({
  triggers: getTriggers(task).map((t) => (t.id === triggerId ? { ...t, ...patch } : t)),
});

/** Config patch that reassigns a trigger to another channel. */
export const moveTrigger = (task, triggerId, newChannelId) => ({
  triggers: getTriggers(task).map((t) =>
    t.id === triggerId ? { ...t, channelId: newChannelId } : t,
  ),
});

/** Config patch that removes a trigger, keeping `activeTriggerId` valid. */
export const removeTrigger = (task, triggerId) => {
  const triggers = getTriggers(task).filter((t) => t.id !== triggerId);
  let activeTriggerId = task?.config?.activeTriggerId;
  if (activeTriggerId === triggerId) activeTriggerId = triggers[0]?.id ?? null;
  return { triggers, activeTriggerId };
};

/** Config patch that marks a trigger as the active (axis-aligning) one. */
export const setActiveTrigger = (triggerId) => ({ activeTriggerId: triggerId });

/**
 * Build the updated task for a dropped virtual TRIGGER device. Shared by the
 * mouse and touch drop paths so both behave identically. The trigger is applied
 * to the task's primary channel and becomes active; the legacy `trigger` key is
 * stripped so the array form is the single source of truth.
 */
export const applyDroppedTrigger = (task, droppedTask) => {
  const channels = getTaskChannels(task);
  const channelId = channels[0]?.id ?? null;
  const { triggers, activeTriggerId } = upsertTriggerForChannel(task, channelId, {
    mode: droppedTask?.config?.mode,
    level: droppedTask?.config?.level ?? 0,
  });
  // Drop the legacy single-trigger key; the array is authoritative now.
  const { trigger: _legacy, ...restConfig } = task.config || {};
  return { ...task, config: { ...restConfig, triggers, activeTriggerId } };
};

