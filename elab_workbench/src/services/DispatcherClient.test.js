import { describe, it, expect, vi, beforeEach } from 'vitest'

// Mock socket.io-client — build a mock that stores handlers so we can trigger them
vi.mock('socket.io-client', () => ({
  io: vi.fn(() => {
    const handlers = {}
    return {
      on: vi.fn((event, cb) => {
        if (!handlers[event]) handlers[event] = []
        handlers[event].push(cb)
      }),
      emit: vi.fn(),
      disconnect: vi.fn(),
      connected: true,
      io: { reconnection: vi.fn(), open: vi.fn() },
      // Helper to trigger server events in tests
      _trigger(event, data) {
        ;(handlers[event] || []).forEach(cb => cb(data))
      },
    }
  }),
}))

// We need a fresh dispatcher instance for each test (the module exports a singleton).
// Re-import after resetting modules.
let DispatcherClient
let SOCKET_EVENTS, APP_EVENTS

beforeEach(async () => {
  vi.resetModules()
  const mod = await import('./DispatcherClient.js')
  DispatcherClient = mod.dispatcher.constructor
  const events = await import('../utils/EventTypes.js')
  SOCKET_EVENTS = events.SOCKET_EVENTS
  APP_EVENTS = events.APP_EVENTS
})

function createDispatcher() {
  return new DispatcherClient()
}

/** Create a connected dispatcher with a triggerable mock socket. */
function createConnectedDispatcher() {
  const d = createDispatcher()
  d.connect('http://test:5000')
  return d
}

describe('DispatcherClient', () => {
  describe('Event Bus (on/off/_emit)', () => {
    it('registers and fires event handlers', () => {
      const d = createDispatcher()
      const handler = vi.fn()
      d.on(APP_EVENTS.ON_DATA_STREAM, handler)
      d._emit(APP_EVENTS.ON_DATA_STREAM, { value: 42 })
      expect(handler).toHaveBeenCalledWith({ value: 42 })
    })

    it('supports multiple handlers for the same event', () => {
      const d = createDispatcher()
      const h1 = vi.fn()
      const h2 = vi.fn()
      d.on(APP_EVENTS.ON_PROVIDER_UPDATE, h1)
      d.on(APP_EVENTS.ON_PROVIDER_UPDATE, h2)
      d._emit(APP_EVENTS.ON_PROVIDER_UPDATE, [{ id: 'p1' }])
      expect(h1).toHaveBeenCalled()
      expect(h2).toHaveBeenCalled()
    })

    it('unregisters a handler with off()', () => {
      const d = createDispatcher()
      const handler = vi.fn()
      d.on(APP_EVENTS.ON_DATA_STREAM, handler)
      d.off(APP_EVENTS.ON_DATA_STREAM, handler)
      d._emit(APP_EVENTS.ON_DATA_STREAM, { value: 99 })
      expect(handler).not.toHaveBeenCalled()
    })

    it('off() does not remove other handlers', () => {
      const d = createDispatcher()
      const h1 = vi.fn()
      const h2 = vi.fn()
      d.on(APP_EVENTS.ON_DATA_STREAM, h1)
      d.on(APP_EVENTS.ON_DATA_STREAM, h2)
      d.off(APP_EVENTS.ON_DATA_STREAM, h1)
      d._emit(APP_EVENTS.ON_DATA_STREAM, {})
      expect(h1).not.toHaveBeenCalled()
      expect(h2).toHaveBeenCalled()
    })

    it('_emit does nothing for events with no handlers', () => {
      const d = createDispatcher()
      // Should not throw
      expect(() => d._emit('nonExistentEvent', {})).not.toThrow()
    })

    it('on() creates handler array for unknown events', () => {
      const d = createDispatcher()
      const handler = vi.fn()
      d.on('customEvent', handler)
      d._emit('customEvent', 'test')
      expect(handler).toHaveBeenCalledWith('test')
    })

    it('on() warns and overwrites when handler list is not an array', () => {
      const d = createDispatcher()
      d.handlers['broken'] = 'not-an-array'
      const spy = vi.spyOn(console, 'warn').mockImplementation(() => {})
      d.on('broken', vi.fn())
      expect(spy).toHaveBeenCalled()
      expect(Array.isArray(d.handlers['broken'])).toBe(true)
      spy.mockRestore()
    })
  })

  describe('connect() — incoming server events', () => {
    it('handles connection_established and sets state', () => {
      const d = createConnectedDispatcher()
      const handler = vi.fn()
      d.on(APP_EVENTS.ON_CONNECTION_ESTABLISHED, handler)

      d.socket._trigger(SOCKET_EVENTS.CONNECTION_ESTABLISHED, {
        session_id: 'sess-1',
        version: '3.2.0',
      })

      expect(d.connected).toBe(true)
      expect(d.sessionId).toBe('sess-1')
      expect(handler).toHaveBeenCalled()
    })

    it('connection_established triggers registerClient and data fetches', () => {
      const d = createConnectedDispatcher()
      d.connected = true

      d.socket._trigger(SOCKET_EVENTS.CONNECTION_ESTABLISHED, {
        session_id: 'sess-2',
      })

      const emitCalls = d.socket.emit.mock.calls.map(c => c[0])
      expect(emitCalls).toContain(SOCKET_EVENTS.REGISTER_CLIENT)
      expect(emitCalls).toContain(SOCKET_EVENTS.GET_AVAILABLE_SCRIPTS)
      expect(emitCalls).toContain(SOCKET_EVENTS.GET_SESSIONS)
    })

    it('handles available_providers', () => {
      const d = createConnectedDispatcher()
      const handler = vi.fn()
      d.on(APP_EVENTS.ON_PROVIDER_UPDATE, handler)

      const providers = [{ id: 'p1', name: 'Sensor' }]
      d.socket._trigger(SOCKET_EVENTS.AVAILABLE_PROVIDERS, { providers })

      expect(d.providers).toEqual(providers)
      expect(handler).toHaveBeenCalledWith(providers)
    })

    it('handles provider_registered (adds new provider)', () => {
      const d = createConnectedDispatcher()
      d.providers = [{ id: 'existing' }]
      const handler = vi.fn()
      d.on(APP_EVENTS.ON_PROVIDER_UPDATE, handler)

      d.socket._trigger(SOCKET_EVENTS.PROVIDER_REGISTERED, {
        provider: { id: 'new-one', name: 'New' },
      })

      expect(d.providers).toHaveLength(2)
      expect(handler).toHaveBeenCalled()
    })

    it('handles provider_registered (does not duplicate existing)', () => {
      const d = createConnectedDispatcher()
      d.providers = [{ id: 'p1' }]

      d.socket._trigger(SOCKET_EVENTS.PROVIDER_REGISTERED, {
        provider: { id: 'p1', name: 'Same' },
      })

      expect(d.providers).toHaveLength(1)
    })

    it('handles provider_disconnected', () => {
      const d = createConnectedDispatcher()
      d.providers = [{ id: 'p1' }, { id: 'p2' }]
      const handler = vi.fn()
      d.on(APP_EVENTS.ON_PROVIDER_UPDATE, handler)

      d.socket._trigger(SOCKET_EVENTS.PROVIDER_DISCONNECTED, {
        provider_id: 'p1',
      })

      expect(d.providers).toEqual([{ id: 'p2' }])
      expect(handler).toHaveBeenCalled()
    })

    it('handles provider_offline', () => {
      const d = createConnectedDispatcher()
      d.providers = [{ id: 'p1' }]
      const handler = vi.fn()
      d.on(APP_EVENTS.ON_PROVIDER_OFFLINE, handler)

      d.socket._trigger(SOCKET_EVENTS.PROVIDER_OFFLINE, { provider_id: 'p1' })

      expect(d.providers).toEqual([])
      expect(handler).toHaveBeenCalledWith({ provider_id: 'p1' })
    })

    it('handles data_stream', () => {
      const d = createConnectedDispatcher()
      const handler = vi.fn()
      d.on(APP_EVENTS.ON_DATA_STREAM, handler)

      d.socket._trigger(SOCKET_EVENTS.DATA_STREAM, { taskId: 't1', value: 42 })

      expect(handler).toHaveBeenCalledWith({ taskId: 't1', value: 42 })
    })

    it('handles session_status', () => {
      const d = createConnectedDispatcher()
      const handler = vi.fn()
      d.on(APP_EVENTS.ON_SESSION_STATUS, handler)

      d.socket._trigger(SOCKET_EVENTS.SESSION_STATUS, { recording: true })
      expect(handler).toHaveBeenCalledWith({ recording: true })
    })

    it('handles available_scripts', () => {
      const d = createConnectedDispatcher()
      const handler = vi.fn()
      d.on(APP_EVENTS.ON_SCRIPTS_UPDATE, handler)

      d.socket._trigger(SOCKET_EVENTS.AVAILABLE_SCRIPTS, ['script1.py'])
      expect(handler).toHaveBeenCalledWith(['script1.py'])
    })

    it('handles replay events', () => {
      const d = createConnectedDispatcher()
      const replayHandler = vi.fn()
      const progressHandler = vi.fn()
      const loadedHandler = vi.fn()
      d.on(APP_EVENTS.ON_REPLAY_STATUS, replayHandler)
      d.on(APP_EVENTS.ON_REPLAY_PROGRESS, progressHandler)
      d.on(APP_EVENTS.ON_REPLAY_LOADED, loadedHandler)

      d.socket._trigger(SOCKET_EVENTS.REPLAY_STATUS, { state: 'playing' })
      d.socket._trigger(SOCKET_EVENTS.REPLAY_PROGRESS, { percent: 50 })
      d.socket._trigger(SOCKET_EVENTS.REPLAY_LOADED, { session_id: 's1' })

      expect(replayHandler).toHaveBeenCalled()
      expect(progressHandler).toHaveBeenCalled()
      expect(loadedHandler).toHaveBeenCalled()
    })

    it('handles session_list and recorded_providers', () => {
      const d = createConnectedDispatcher()
      const sessionHandler = vi.fn()
      const recordedHandler = vi.fn()
      d.on(APP_EVENTS.ON_SESSION_LIST, sessionHandler)
      d.on(APP_EVENTS.ON_RECORDED_PROVIDERS, recordedHandler)

      d.socket._trigger(SOCKET_EVENTS.SESSION_LIST, { sessions: [] })
      d.socket._trigger(SOCKET_EVENTS.RECORDED_PROVIDERS, { providers: [] })

      expect(sessionHandler).toHaveBeenCalled()
      expect(recordedHandler).toHaveBeenCalled()
    })

    it('handles provider_meta_changed', () => {
      const d = createConnectedDispatcher()
      const handler = vi.fn()
      d.on(APP_EVENTS.ON_PROVIDER_META_CHANGED, handler)

      d.socket._trigger(SOCKET_EVENTS.PROVIDER_META_CHANGED, { id: 'p1' })
      expect(handler).toHaveBeenCalledWith({ id: 'p1' })
    })

    it('handles task_rejected', () => {
      const d = createConnectedDispatcher()
      const handler = vi.fn()
      d.on(APP_EVENTS.ON_TASK_REJECTED, handler)
      const spy = vi.spyOn(console, 'warn').mockImplementation(() => {})

      d.socket._trigger(SOCKET_EVENTS.TASK_REJECTED, { reason: 'busy' })

      expect(handler).toHaveBeenCalledWith({ reason: 'busy' })
      spy.mockRestore()
    })

    it('handles active_tasks_snapshot', () => {
      const d = createConnectedDispatcher()
      const handler = vi.fn()
      d.on(APP_EVENTS.ON_ACTIVE_TASKS_SNAPSHOT, handler)

      d.socket._trigger(SOCKET_EVENTS.ACTIVE_TASKS_SNAPSHOT, { tasks: [] })
      expect(handler).toHaveBeenCalledWith({ tasks: [] })
    })
  })

  describe('connect() — disconnect and reconnect handling', () => {
    it('handles disconnect event', () => {
      const d = createConnectedDispatcher()
      d.connected = true
      const handler = vi.fn()
      d.on(APP_EVENTS.ON_DISCONNECT, handler)
      const spy = vi.spyOn(console, 'error').mockImplementation(() => {})

      d.socket._trigger(SOCKET_EVENTS.DISCONNECT, 'transport close')

      expect(d.connected).toBe(false)
      expect(handler).toHaveBeenCalledWith({ reason: 'transport close' })
      spy.mockRestore()
    })

    it('handles io server disconnect with reconnect attempt', () => {
      const d = createConnectedDispatcher()
      d.connected = true
      const spy = vi.spyOn(console, 'error').mockImplementation(() => {})

      d.socket._trigger(SOCKET_EVENTS.DISCONNECT, 'io server disconnect')

      expect(d.connected).toBe(false)
      expect(d.socket.io.reconnection).toHaveBeenCalledWith(true)
      spy.mockRestore()
    })

    it('handles connect_error', () => {
      const d = createConnectedDispatcher()
      const handler = vi.fn()
      d.on(APP_EVENTS.ON_CONNECTION_ERROR, handler)
      const spy = vi.spyOn(console, 'error').mockImplementation(() => {})

      d.socket._trigger(SOCKET_EVENTS.CONNECT_ERROR, { message: 'timeout' })

      expect(handler).toHaveBeenCalledWith({ error: 'timeout' })
      spy.mockRestore()
    })

    it('handles reconnect event and resubscribes tasks', () => {
      const d = createConnectedDispatcher()
      d.socket.connected = true
      const handler = vi.fn()
      d.on(APP_EVENTS.ON_RECONNECT, handler)

      // Set up pre-existing subscriptions
      d.taskSubscriptions.set('task-a', new Set([vi.fn()]))
      const spy = vi.spyOn(console, 'log').mockImplementation(() => {})

      d.socket._trigger('reconnect', 3)

      expect(d.connected).toBe(true)
      expect(handler).toHaveBeenCalledWith({ attemptNumber: 3 })
      // Verify resubscription emitted
      const subscribeCalls = d.socket.emit.mock.calls.filter(
        c => c[0] === SOCKET_EVENTS.SUBSCRIBE_TASK
      )
      expect(subscribeCalls.length).toBeGreaterThanOrEqual(1)
      spy.mockRestore()
    })

    it('handles reconnect_error', () => {
      const d = createConnectedDispatcher()
      const handler = vi.fn()
      d.on(APP_EVENTS.ON_RECONNECT_ERROR, handler)
      const spy = vi.spyOn(console, 'error').mockImplementation(() => {})

      d.socket._trigger('reconnect_error', { message: 'net error' })

      expect(handler).toHaveBeenCalledWith({ error: 'net error' })
      spy.mockRestore()
    })

    it('handles reconnect_failed', () => {
      const d = createConnectedDispatcher()
      const handler = vi.fn()
      d.on(APP_EVENTS.ON_RECONNECT_FAILED, handler)
      const spy = vi.spyOn(console, 'error').mockImplementation(() => {})

      d.socket._trigger('reconnect_failed')

      expect(handler).toHaveBeenCalled()
      spy.mockRestore()
    })
  })

  describe('Task Subscriptions', () => {
    it('subscribe adds callback and emits SUBSCRIBE_TASK', () => {
      const d = createDispatcher()
      d.socket = { connected: true, emit: vi.fn() }
      d.connected = true
      const cb = vi.fn()
      d.subscribe('task-1', cb)
      expect(d.taskSubscriptions.has('task-1')).toBe(true)
      expect(d.taskSubscriptions.get('task-1').has(cb)).toBe(true)
      expect(d.socket.emit).toHaveBeenCalledWith(SOCKET_EVENTS.SUBSCRIBE_TASK, { taskId: 'task-1' })
    })

    it('second subscriber does not re-emit SUBSCRIBE_TASK', () => {
      const d = createDispatcher()
      d.socket = { connected: true, emit: vi.fn() }
      d.connected = true
      d.subscribe('task-1', vi.fn())
      d.subscribe('task-1', vi.fn())
      // Only emitted once
      const subscribeCalls = d.socket.emit.mock.calls.filter(
        c => c[0] === SOCKET_EVENTS.SUBSCRIBE_TASK
      )
      expect(subscribeCalls.length).toBe(1)
    })

    it('subscribe does not emit when socket is disconnected', () => {
      const d = createDispatcher()
      d.socket = { connected: false, emit: vi.fn() }
      d.subscribe('task-1', vi.fn())
      expect(d.socket.emit).not.toHaveBeenCalled()
      // But subscription is still tracked locally
      expect(d.taskSubscriptions.has('task-1')).toBe(true)
    })

    it('unsubscribe removes callback and emits UNSUBSCRIBE_TASK when last', () => {
      const d = createDispatcher()
      d.socket = { connected: true, emit: vi.fn() }
      d.connected = true
      const cb = vi.fn()
      d.subscribe('task-1', cb)
      d.unsubscribe('task-1', cb)
      expect(d.taskSubscriptions.has('task-1')).toBe(false)
      expect(d.socket.emit).toHaveBeenCalledWith(SOCKET_EVENTS.UNSUBSCRIBE_TASK, { taskId: 'task-1' })
    })

    it('unsubscribe does not emit when other subscribers remain', () => {
      const d = createDispatcher()
      d.socket = { connected: true, emit: vi.fn() }
      d.connected = true
      const cb1 = vi.fn()
      const cb2 = vi.fn()
      d.subscribe('task-1', cb1)
      d.subscribe('task-1', cb2)
      d.unsubscribe('task-1', cb1)
      const unsubCalls = d.socket.emit.mock.calls.filter(
        c => c[0] === SOCKET_EVENTS.UNSUBSCRIBE_TASK
      )
      expect(unsubCalls.length).toBe(0)
      expect(d.taskSubscriptions.get('task-1').size).toBe(1)
    })

    it('unsubscribe on unknown task does not crash', () => {
      const d = createDispatcher()
      d.socket = { connected: true, emit: vi.fn() }
      expect(() => d.unsubscribe('unknown', vi.fn())).not.toThrow()
    })

    it('_resubscribeAllTasks re-emits for all active subscriptions', () => {
      const d = createDispatcher()
      d.socket = { connected: true, emit: vi.fn() }
      d.connected = true
      d.subscribe('task-1', vi.fn())
      d.subscribe('task-2', vi.fn())
      d.socket.emit.mockClear()
      d._resubscribeAllTasks()
      const calls = d.socket.emit.mock.calls.filter(c => c[0] === SOCKET_EVENTS.SUBSCRIBE_TASK)
      expect(calls.length).toBe(2)
    })
  })

  describe('Outgoing Commands', () => {
    it('sendTaskRequest emits TASK_REQUEST', () => {
      const d = createDispatcher()
      d.socket = { emit: vi.fn() }
      d.connected = true
      d.sendTaskRequest('provider-1', { id: 'task-1', type: 'SENSOR' })
      expect(d.socket.emit).toHaveBeenCalledWith(
        SOCKET_EVENTS.TASK_REQUEST,
        expect.objectContaining({ provider_id: 'provider-1', task: { id: 'task-1', type: 'SENSOR' } })
      )
    })

    it('sendControlCommand emits CMD_CONTROL', () => {
      const d = createDispatcher()
      d.socket = { emit: vi.fn() }
      d.connected = true
      d.sendControlCommand('provider-1', { action: 'START' })
      expect(d.socket.emit).toHaveBeenCalledWith(
        SOCKET_EVENTS.CMD_CONTROL,
        expect.objectContaining({ provider_id: 'provider-1', command: { action: 'START' } })
      )
    })

    it('assignTaskToSlot emits TASK_ASSIGNED', () => {
      const d = createDispatcher()
      d.socket = { emit: vi.fn() }
      d.assignTaskToSlot(2, 'task-x')
      expect(d.socket.emit).toHaveBeenCalledWith(SOCKET_EVENTS.TASK_ASSIGNED, { slot: 2, taskId: 'task-x' })
    })

    it('unassignTaskFromSlot emits TASK_UNASSIGNED', () => {
      const d = createDispatcher()
      d.socket = { emit: vi.fn() }
      d.unassignTaskFromSlot(3, 'task-y')
      expect(d.socket.emit).toHaveBeenCalledWith(SOCKET_EVENTS.TASK_UNASSIGNED, { slot: 3, taskId: 'task-y' })
    })

    it('does not crash when socket is null', () => {
      const d = createDispatcher()
      d.socket = null
      expect(() => d.sendTaskRequest('p', {})).not.toThrow()
      expect(() => d.sendControlCommand('p', {})).not.toThrow()
    })

    it('registerClient does nothing when not connected', () => {
      const d = createDispatcher()
      d.socket = { emit: vi.fn() }
      d.connected = false
      d.registerClient()
      expect(d.socket.emit).not.toHaveBeenCalled()
    })

    it('getAvailableScripts emits GET_AVAILABLE_SCRIPTS', () => {
      const d = createDispatcher()
      d.socket = { emit: vi.fn() }
      d.getAvailableScripts()
      expect(d.socket.emit).toHaveBeenCalledWith(SOCKET_EVENTS.GET_AVAILABLE_SCRIPTS)
    })

    it('startClientScript emits START_CLIENT_SCRIPT', () => {
      const d = createDispatcher()
      d.socket = { emit: vi.fn() }
      d.startClientScript('MyClient.py')
      expect(d.socket.emit).toHaveBeenCalledWith(SOCKET_EVENTS.START_CLIENT_SCRIPT, { filename: 'MyClient.py' })
    })

    it('stopClientScript emits STOP_CLIENT_SCRIPT', () => {
      const d = createDispatcher()
      d.socket = { emit: vi.fn() }
      d.stopClientScript('MyClient.py')
      expect(d.socket.emit).toHaveBeenCalledWith(SOCKET_EVENTS.STOP_CLIENT_SCRIPT, { filename: 'MyClient.py' })
    })
  })

  describe('Session & Replay commands', () => {
    it('startSession emits SESSION_START', () => {
      const d = createDispatcher()
      d.socket = { emit: vi.fn() }
      d.startSession('my-session')
      expect(d.socket.emit).toHaveBeenCalledWith(SOCKET_EVENTS.SESSION_START, { session_id: 'my-session' })
    })

    it('stopSession emits SESSION_STOP', () => {
      const d = createDispatcher()
      d.socket = { emit: vi.fn() }
      d.stopSession()
      expect(d.socket.emit).toHaveBeenCalledWith(SOCKET_EVENTS.SESSION_STOP, {})
    })

    it('sendReplayAction emits REPLAY_ACTION', () => {
      const d = createDispatcher()
      d.socket = { emit: vi.fn() }
      d.sendReplayAction('play', null)
      expect(d.socket.emit).toHaveBeenCalledWith(SOCKET_EVENTS.REPLAY_ACTION, { action: 'play', value: null })
    })

    it('deleteSession emits DELETE_SESSION', () => {
      const d = createDispatcher()
      d.socket = { emit: vi.fn() }
      d.deleteSession('sess-123')
      expect(d.socket.emit).toHaveBeenCalledWith(SOCKET_EVENTS.DELETE_SESSION, { session_id: 'sess-123' })
    })

    it('getSessions emits GET_SESSIONS', () => {
      const d = createDispatcher()
      d.socket = { emit: vi.fn() }
      d.getSessions()
      expect(d.socket.emit).toHaveBeenCalledWith(SOCKET_EVENTS.GET_SESSIONS)
    })

    it('loadSession emits REPLAY_LOAD', () => {
      const d = createDispatcher()
      d.socket = { emit: vi.fn() }
      d.loadSession('sess-456')
      expect(d.socket.emit).toHaveBeenCalledWith(SOCKET_EVENTS.REPLAY_LOAD, { session_id: 'sess-456' })
    })

    it('getRecordedProviders emits GET_RECORDED_PROVIDERS', () => {
      const d = createDispatcher()
      d.socket = { emit: vi.fn() }
      d.getRecordedProviders('sess-789')
      expect(d.socket.emit).toHaveBeenCalledWith(SOCKET_EVENTS.GET_RECORDED_PROVIDERS, { session_id: 'sess-789' })
    })

    it('sendReplayAction with speed and value', () => {
      const d = createDispatcher()
      d.socket = { emit: vi.fn() }
      d.sendReplayAction('speed', 2.0)
      expect(d.socket.emit).toHaveBeenCalledWith(SOCKET_EVENTS.REPLAY_ACTION, { action: 'speed', value: 2.0 })
    })
  })

  describe('disconnect()', () => {
    it('disconnects socket and resets state', () => {
      const d = createDispatcher()
      const mockDisconnect = vi.fn()
      d.socket = { disconnect: mockDisconnect }
      d.connected = true
      d.disconnect()
      expect(mockDisconnect).toHaveBeenCalled()
      expect(d.socket).toBeNull()
      expect(d.connected).toBe(false)
    })

    it('disconnect when already null does nothing', () => {
      const d = createDispatcher()
      d.socket = null
      d.connected = false
      expect(() => d.disconnect()).not.toThrow()
    })
  })

  describe('connect() returns this', () => {
    it('connect returns the dispatcher instance for chaining', () => {
      const d = createDispatcher()
      const result = d.connect('http://test:5000')
      expect(result).toBe(d)
    })
  })
})
