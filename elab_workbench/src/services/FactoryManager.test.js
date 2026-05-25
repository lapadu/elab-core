import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

// Mock PluginAdapter as a class constructor
class MockAdapter {
  constructor() { this.register = vi.fn(); this.unregister = vi.fn() }
}
vi.mock('../plugins/core/PluginAdapter', () => ({
  default: vi.fn(function () { return new MockAdapter() }),
}))

// Mock DispatcherClient (no real socket needed)
vi.mock('./DispatcherClient', () => ({
  default: { on: vi.fn(), off: vi.fn(), _emit: vi.fn() },
}))

import { factoryManager } from './FactoryManager.js'

describe('FactoryManager', () => {
  beforeEach(() => {
    // Clear all factories and pending stops between tests.
    factoryManager.factories.clear()
    factoryManager.pendingStops.forEach(tid => clearTimeout(tid))
    factoryManager.pendingStops.clear()
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  const mockTask = { id: 'task-1', originalId: 'task-1' }
  const mockPlugin = {
    simulation: { factory: vi.fn(() => vi.fn()) },
  }

  it('startFactory creates a new factory entry', () => {
    factoryManager.startFactory(mockTask, mockPlugin)
    expect(factoryManager.factories.has('task-1')).toBe(true)
    expect(mockPlugin.simulation.factory).toHaveBeenCalledWith(mockTask, expect.anything())
  })

  it('startFactory does nothing if factory already running', () => {
    factoryManager.startFactory(mockTask, mockPlugin)
    mockPlugin.simulation.factory.mockClear()
    factoryManager.startFactory(mockTask, mockPlugin)
    expect(mockPlugin.simulation.factory).not.toHaveBeenCalled()
  })

  it('startFactory cancels a pending stop', () => {
    factoryManager.startFactory(mockTask, mockPlugin)
    factoryManager.scheduleStop('task-1')
    expect(factoryManager.pendingStops.has('task-1')).toBe(true)

    // Starting again should cancel the pending stop
    factoryManager.startFactory(mockTask, mockPlugin)
    expect(factoryManager.pendingStops.has('task-1')).toBe(false)
  })

  it('scheduleStop removes factory after 500ms', () => {
    factoryManager.startFactory(mockTask, mockPlugin)
    factoryManager.scheduleStop('task-1')
    expect(factoryManager.factories.has('task-1')).toBe(true)

    vi.advanceTimersByTime(500)
    expect(factoryManager.factories.has('task-1')).toBe(false)
  })

  it('performStop does not remove factory if subscribers remain', () => {
    factoryManager.startFactory(mockTask, mockPlugin)
    factoryManager.subscribe('task-1', 'widget-A')
    factoryManager.performStop('task-1')
    expect(factoryManager.factories.has('task-1')).toBe(true)
  })

  it('subscribe and unsubscribe manage subscriber sets', () => {
    factoryManager.startFactory(mockTask, mockPlugin)
    factoryManager.subscribe('task-1', 'widget-A')
    factoryManager.subscribe('task-1', 'widget-B')
    expect(factoryManager.factories.get('task-1').subscribers.size).toBe(2)

    factoryManager.unsubscribe('task-1', 'widget-A')
    expect(factoryManager.factories.get('task-1').subscribers.size).toBe(1)
  })

  it('unsubscribe triggers scheduleStop when last subscriber leaves', () => {
    factoryManager.startFactory(mockTask, mockPlugin)
    factoryManager.subscribe('task-1', 'widget-A')
    factoryManager.unsubscribe('task-1', 'widget-A')
    // Should have a pending stop
    expect(factoryManager.pendingStops.has('task-1')).toBe(true)
    vi.advanceTimersByTime(500)
    expect(factoryManager.factories.has('task-1')).toBe(false)
  })

  it('subscribe cancels a pending stop', () => {
    factoryManager.startFactory(mockTask, mockPlugin)
    factoryManager.subscribe('task-1', 'widget-A')
    factoryManager.unsubscribe('task-1', 'widget-A')
    // Pending stop scheduled
    factoryManager.subscribe('task-1', 'widget-B')
    expect(factoryManager.pendingStops.has('task-1')).toBe(false)
    vi.advanceTimersByTime(500)
    // Factory should still exist
    expect(factoryManager.factories.has('task-1')).toBe(true)
  })

  it('performStop calls cleanup and unregister', () => {
    const cleanup = vi.fn()
    const pluginWithCleanup = {
      simulation: { factory: vi.fn(() => cleanup) },
    }
    factoryManager.startFactory(mockTask, pluginWithCleanup)
    const factory = factoryManager.factories.get('task-1')
    const unregSpy = vi.spyOn(factory.adapter, 'unregister')

    factoryManager.performStop('task-1')
    expect(cleanup).toHaveBeenCalled()
    expect(unregSpy).toHaveBeenCalled()
  })
})
