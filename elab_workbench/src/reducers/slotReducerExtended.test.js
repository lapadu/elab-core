import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('../services/FactoryManager', () => ({
  factoryManager: { startFactory: vi.fn() },
}))
vi.mock('../components/PluginRegistry', () => ({
  getPlugin: vi.fn(() => null),
}))

import {
  slotReducer,
  initialSlotState,
  createTaskInstanceCache,
} from './slotReducer.js'

describe('slotReducer – extended coverage', () => {
  let cache
  beforeEach(() => {
    cache = createTaskInstanceCache()
  })

  describe('UPDATE_TASK', () => {
    it('updates an existing slot task', () => {
      const baseTask = { id: 'task-1', groupId: 'p', providerId: 'prov' }
      let s = slotReducer(initialSlotState, { type: 'DROP_TASK', index: 0, baseTask, cache })
      const updated = { ...s[0], config: { timeWindow: 5 } }
      s = slotReducer(s, { type: 'UPDATE_TASK', index: 0, task: updated, cache })
      expect(s[0].config.timeWindow).toBe(5)
    })

    it('updates the cache reference', () => {
      const baseTask = { id: 'task-1', groupId: 'p' }
      let s = slotReducer(initialSlotState, { type: 'DROP_TASK', index: 0, baseTask, cache })
      const updated = { ...s[0], config: { yMin: -3, yMax: 3 } }
      slotReducer(s, { type: 'UPDATE_TASK', index: 0, task: updated, cache })
      expect(cache.get('task-1').config.yMin).toBe(-3)
    })
  })

  describe('ADD_CHANNEL', () => {
    it('adds an extra channel to a task', () => {
      const baseTask = { id: 'scope-1', groupId: 'scope', type: 'SENSOR', is_recorded: true }
      let s = slotReducer(initialSlotState, { type: 'DROP_TASK', index: 0, baseTask, cache })
      const channel = { id: 'ch2', name: 'Channel 2', color: '#ff0000', config: {} }
      s = slotReducer(s, { type: 'ADD_CHANNEL', index: 0, channelTask: channel, cache })
      expect(s[0].extraChannels.length).toBe(1)
      expect(s[0].extraChannels[0].id).toBe('ch2')
    })

    it('does not add duplicate channels', () => {
      const baseTask = { id: 'scope-1', groupId: 'scope', type: 'SENSOR', is_recorded: true }
      let s = slotReducer(initialSlotState, { type: 'DROP_TASK', index: 0, baseTask, cache })
      const channel = { id: 'ch2', name: 'Channel 2', color: '#ff0000' }
      s = slotReducer(s, { type: 'ADD_CHANNEL', index: 0, channelTask: channel, cache })
      s = slotReducer(s, { type: 'ADD_CHANNEL', index: 0, channelTask: channel, cache })
      expect(s[0].extraChannels.length).toBe(1)
    })

    it('returns unchanged state if target slot is empty', () => {
      const channel = { id: 'ch2', name: 'Channel 2', color: '#ff0000' }
      const s = slotReducer(initialSlotState, { type: 'ADD_CHANNEL', index: 3, channelTask: channel, cache })
      expect(s).toEqual(initialSlotState)
    })
  })

  describe('recorded vs. live task identity', () => {
    const liveTask = { id: 'sensor_1', groupId: 'scope', type: 'SENSOR' }
    const recordedTask = {
      id: 'rec_sensor_1',
      originalId: 'sensor_1',
      groupId: 'scope',
      type: 'SENSOR',
      is_recorded: true,
    }

    it('keeps separate instances for a recording and its live source', () => {
      let s = slotReducer(initialSlotState, { type: 'DROP_TASK', index: 0, baseTask: liveTask, cache })
      s = slotReducer(s, { type: 'DROP_TASK', index: 1, baseTask: recordedTask, cache })

      expect(s[0].id).toBe('sensor_1')
      expect(s[0].is_recorded).toBeFalsy()
      expect(s[1].id).toBe('rec_sensor_1')
      expect(s[1].is_recorded).toBe(true)
      expect(s[1]).not.toBe(s[0])
    })

    it('does not evict the live cache entry when the recording is removed', () => {
      let s = slotReducer(initialSlotState, { type: 'DROP_TASK', index: 0, baseTask: liveTask, cache })
      s = slotReducer(s, { type: 'DROP_TASK', index: 1, baseTask: recordedTask, cache })
      s = slotReducer(s, { type: 'REMOVE_TASK', index: 1, cache })

      expect(cache.has('sensor_1')).toBe(true)
      expect(cache.has('rec_sensor_1')).toBe(false)
      expect(s[0].id).toBe('sensor_1')
    })

    it('REBIND_PROVIDER leaves recorded tasks untouched', () => {
      let s = slotReducer(initialSlotState, { type: 'DROP_TASK', index: 0, baseTask: recordedTask, cache })
      s = slotReducer(s, {
        type: 'REBIND_PROVIDER',
        providers: [{ id: 'prov-new', tasks: [{ id: 'sensor_1', groupId: 'scope' }] }],
        cache,
      })
      expect(s[0].id).toBe('rec_sensor_1')
    })
  })

  describe('REBIND_PROVIDER', () => {
    it('updates task when provider reconnects with new ID', () => {
      const baseTask = { id: 'task-1', groupId: 'freq_counter', providerId: 'old-prov', type: 'SENSOR' }
      let s = slotReducer(initialSlotState, { type: 'DROP_TASK', index: 0, baseTask, cache })

      const newProviders = [{
        id: 'new-prov',
        tasks: [{ id: 'task-new', groupId: 'freq_counter', name: 'Freq Counter v2', config: { unit: 'Hz' } }],
      }]

      s = slotReducer(s, { type: 'REBIND_PROVIDER', providers: newProviders, cache })
      expect(s[0].providerId).toBe('new-prov')
      expect(s[0].id).toBe('task-new')
    })

    it('does not touch virtual tasks', () => {
      const baseTask = { id: 'virt-1', groupId: 'sim', providerId: 'old', virtual: true }
      let s = slotReducer(initialSlotState, { type: 'DROP_TASK', index: 0, baseTask, cache })
      const providers = [{ id: 'new', tasks: [{ id: 'new-t', groupId: 'sim' }] }]
      s = slotReducer(s, { type: 'REBIND_PROVIDER', providers, cache })
      expect(s[0].providerId).toBe('old') // unchanged
    })

    it('does not rebind if current provider is still present', () => {
      const baseTask = { id: 'task-1', groupId: 'fc', providerId: 'prov-A' }
      let s = slotReducer(initialSlotState, { type: 'DROP_TASK', index: 0, baseTask, cache })
      const providers = [
        { id: 'prov-A', tasks: [{ id: 'task-1', groupId: 'fc' }] },
        { id: 'prov-B', tasks: [{ id: 'task-2', groupId: 'fc' }] },
      ]
      s = slotReducer(s, { type: 'REBIND_PROVIDER', providers, cache })
      expect(s[0].providerId).toBe('prov-A') // unchanged
    })
  })

  describe('RESTORE_SNAPSHOT', () => {
    it('returns unchanged state for invalid slotMap', () => {
      const s = slotReducer(initialSlotState, {
        type: 'RESTORE_SNAPSHOT', slotMap: null, providers: [], cache,
      })
      expect(s).toBe(initialSlotState)
    })

    it('skips unresolvable task IDs', () => {
      const providers = [{ id: 'p1', tasks: [{ id: 'known-task', groupId: 'x' }] }]
      const s = slotReducer(initialSlotState, {
        type: 'RESTORE_SNAPSHOT',
        slotMap: { 0: 'unknown-task', 1: 'known-task' },
        providers,
        cache,
      })
      expect(s[0]).toBeNull()
      expect(s[1]).not.toBeNull()
      expect(s[1].id).toBe('known-task')
    })
  })

  describe('default case', () => {
    it('returns state unchanged for unknown action', () => {
      const s = slotReducer(initialSlotState, { type: 'UNKNOWN_ACTION', cache })
      expect(s).toBe(initialSlotState)
    })
  })
})
