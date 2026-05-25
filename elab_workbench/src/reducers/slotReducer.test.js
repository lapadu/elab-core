import { describe, it, expect, vi, beforeEach } from 'vitest'

// Mock the side-effect imports so the reducer can run in isolation.
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

describe('slotReducer', () => {
  let cache
  beforeEach(() => {
    cache = createTaskInstanceCache()
  })

  it('drops a task into a slot', () => {
    const baseTask = { id: 'task-1', groupId: 'demo', providerId: 'p1', type: 'SENSOR' }
    const next = slotReducer(initialSlotState, {
      type: 'DROP_TASK',
      index: 0,
      baseTask,
      cache,
    })
    expect(next[0]).not.toBeNull()
    expect(next[0].id).toBe('task-1')
    expect(next[0].inputs).toEqual({ source: null })
  })

  it('reuses cached instance on repeat drop', () => {
    const baseTask = { id: 'task-1', groupId: 'demo', providerId: 'p1' }
    const a = slotReducer(initialSlotState, {
      type: 'DROP_TASK', index: 0, baseTask, cache,
    })
    const b = slotReducer(a, {
      type: 'DROP_TASK', index: 1, baseTask, cache,
    })
    expect(b[0]).toBe(b[1]) // same instance reference
  })

  it('removes a task and frees the cache when no other slot uses it', () => {
    const baseTask = { id: 'task-1', groupId: 'demo', providerId: 'p1' }
    const a = slotReducer(initialSlotState, {
      type: 'DROP_TASK', index: 0, baseTask, cache,
    })
    expect(cache.size).toBe(1)
    const b = slotReducer(a, { type: 'REMOVE_TASK', index: 0, cache })
    expect(b[0]).toBeNull()
    expect(cache.size).toBe(0)
  })

  it('keeps cache entry while another slot still uses the task', () => {
    const baseTask = { id: 'task-1', groupId: 'demo', providerId: 'p1' }
    let s = slotReducer(initialSlotState, { type: 'DROP_TASK', index: 0, baseTask, cache })
    s = slotReducer(s, { type: 'DROP_TASK', index: 1, baseTask, cache })
    s = slotReducer(s, { type: 'REMOVE_TASK', index: 0, cache })
    expect(cache.size).toBe(1)
    expect(s[1]).not.toBeNull()
  })

  it('CLEAR_ALL resets state and cache', () => {
    const baseTask = { id: 'task-1', groupId: 'demo' }
    let s = slotReducer(initialSlotState, { type: 'DROP_TASK', index: 0, baseTask, cache })
    s = slotReducer(s, { type: 'CLEAR_ALL', cache })
    expect(s).toEqual(initialSlotState)
    expect(cache.size).toBe(0)
  })

  it('RESTORE_SNAPSHOT only fills empty slots', () => {
    const existing = { id: 'existing', groupId: 'p' }
    const slots = { ...initialSlotState, 0: existing }
    const providers = [
      { id: 'prov-1', tasks: [{ id: 'task-from-server', groupId: 'p' }] },
    ]
    const next = slotReducer(slots, {
      type: 'RESTORE_SNAPSHOT',
      slotMap: { 0: 'task-from-server', 2: 'task-from-server' },
      providers,
      cache,
    })
    expect(next[0]).toBe(existing)        // unchanged
    expect(next[2]?.id).toBe('task-from-server')
  })

  it('isolated caches do not leak between reducer instances', () => {
    const cache1 = createTaskInstanceCache()
    const cache2 = createTaskInstanceCache()
    const baseTask = { id: 't', groupId: 'p' }
    slotReducer(initialSlotState, { type: 'DROP_TASK', index: 0, baseTask, cache: cache1 })
    expect(cache1.size).toBe(1)
    expect(cache2.size).toBe(0)
  })
})
