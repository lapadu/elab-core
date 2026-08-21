import { describe, it, expect } from 'vitest';
import {
  getTaskChannels,
  taskSupportsTrigger,
  makeTriggerId,
  getTriggers,
  getActiveTrigger,
  upsertTriggerForChannel,
  patchTrigger,
  moveTrigger,
  removeTrigger,
  setActiveTrigger,
  applyDroppedTrigger,
} from './configUtils.js';

const taskWithChannels = () => ({
  id: 'w1',
  name: 'Scope',
  inputs: { source: { id: 'chA', name: 'A', color: '#f00' } },
  extraChannels: [{ id: 'chB', name: 'B', color: '#0f0' }],
  config: {},
});

describe('configUtils channels', () => {
  it('lists primary and extra channels de-duplicated', () => {
    const channels = getTaskChannels(taskWithChannels());
    expect(channels.map((c) => c.id)).toEqual(['chA', 'chB']);
  });

  it('uses the task itself as the only channel in single-source mode', () => {
    const task = { id: 'w', originalId: 'orig', name: 'X', config: { singleSource: true } };
    expect(getTaskChannels(task)).toEqual([{ id: 'orig', name: 'X', color: undefined }]);
  });

  it('reports trigger support for any task exposing a channel', () => {
    expect(taskSupportsTrigger(taskWithChannels())).toBe(true);
    expect(taskSupportsTrigger({ id: 'x', config: {} })).toBe(false);
    expect(taskSupportsTrigger({ id: 'm', type: 'MEASURE', config: {} })).toBe(true);
  });
});

describe('configUtils trigger model', () => {
  it('generates unique ids', () => {
    expect(makeTriggerId()).not.toBe(makeTriggerId());
  });

  it('migrates a legacy single trigger into the array form', () => {
    const task = { config: { trigger: { channelId: 'chA', mode: 'rising', level: 1 } } };
    const triggers = getTriggers(task);
    expect(triggers).toHaveLength(1);
    expect(triggers[0]).toMatchObject({ channelId: 'chA', mode: 'rising', level: 1, pretrigger: 5 });
    expect(getActiveTrigger(task)).toMatchObject({ channelId: 'chA' });
  });

  it('adds a trigger for a channel and makes it active', () => {
    const task = taskWithChannels();
    const { triggers, activeTriggerId } = upsertTriggerForChannel(task, 'chA', { mode: 'falling', level: 2 });
    expect(triggers).toHaveLength(1);
    expect(triggers[0]).toMatchObject({ channelId: 'chA', mode: 'falling', level: 2 });
    expect(activeTriggerId).toBe(triggers[0].id);
  });

  it('replaces an existing trigger on the same channel instead of duplicating', () => {
    const task = taskWithChannels();
    const first = upsertTriggerForChannel(task, 'chA', { mode: 'rising' });
    const next = upsertTriggerForChannel({ ...task, config: { triggers: first.triggers } }, 'chA', { mode: 'level' });
    expect(next.triggers).toHaveLength(1);
    expect(next.triggers[0].mode).toBe('level');
  });

  it('patches a single trigger without touching others', () => {
    const t1 = { id: 't1', channelId: 'chA', mode: 'rising', level: 0 };
    const t2 = { id: 't2', channelId: 'chB', mode: 'rising', level: 0 };
    const task = { config: { triggers: [t1, t2] } };
    const { triggers } = patchTrigger(task, 't2', { level: 5 });
    expect(triggers[0]).toEqual(t1);
    expect(triggers[1]).toMatchObject({ id: 't2', level: 5 });
  });

  it('moves a trigger to another channel', () => {
    const task = { config: { triggers: [{ id: 't1', channelId: 'chA', mode: 'rising', level: 0 }] } };
    const { triggers } = moveTrigger(task, 't1', 'chB');
    expect(triggers[0].channelId).toBe('chB');
  });

  it('removes a trigger and reassigns the active id when needed', () => {
    const task = {
      config: {
        triggers: [
          { id: 't1', channelId: 'chA', mode: 'rising', level: 0 },
          { id: 't2', channelId: 'chB', mode: 'rising', level: 0 },
        ],
        activeTriggerId: 't1',
      },
    };
    const { triggers, activeTriggerId } = removeTrigger(task, 't1');
    expect(triggers.map((t) => t.id)).toEqual(['t2']);
    expect(activeTriggerId).toBe('t2');
  });

  it('sets the active trigger id', () => {
    expect(setActiveTrigger('abc')).toEqual({ activeTriggerId: 'abc' });
  });

  it('applies a dropped trigger to the primary channel and strips the legacy key', () => {
    const task = { ...taskWithChannels(), config: { trigger: { channelId: 'chA', mode: 'old' }, timeWindow: 5 } };
    const dropped = { type: 'TRIGGER', config: { mode: 'falling', level: 3 } };
    const next = applyDroppedTrigger(task, dropped);
    expect(next.config.trigger).toBeUndefined();
    expect(next.config.timeWindow).toBe(5);
    expect(next.config.triggers).toHaveLength(1);
    expect(next.config.triggers[0]).toMatchObject({ channelId: 'chA', mode: 'falling', level: 3 });
    expect(next.config.activeTriggerId).toBe(next.config.triggers[0].id);
  });
});
