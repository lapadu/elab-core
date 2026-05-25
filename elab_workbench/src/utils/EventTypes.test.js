import { describe, it, expect } from 'vitest'
import { SOCKET_EVENTS, APP_EVENTS } from './EventTypes.js'

describe('EventTypes', () => {
  describe('SOCKET_EVENTS', () => {
    it('is a non-empty object', () => {
      expect(typeof SOCKET_EVENTS).toBe('object')
      expect(Object.keys(SOCKET_EVENTS).length).toBeGreaterThan(0)
    })

    it('all values are strings', () => {
      Object.values(SOCKET_EVENTS).forEach(v => {
        expect(typeof v).toBe('string')
      })
    })

    it('has no duplicate values', () => {
      const values = Object.values(SOCKET_EVENTS)
      const unique = new Set(values)
      expect(unique.size).toBe(values.length)
    })

    it('contains essential connection events', () => {
      expect(SOCKET_EVENTS.CONNECTION_ESTABLISHED).toBeDefined()
      expect(SOCKET_EVENTS.DISCONNECT).toBeDefined()
      expect(SOCKET_EVENTS.CONNECT_ERROR).toBeDefined()
    })

    it('contains essential data events', () => {
      expect(SOCKET_EVENTS.DATA_STREAM).toBeDefined()
      expect(SOCKET_EVENTS.AVAILABLE_PROVIDERS).toBeDefined()
      expect(SOCKET_EVENTS.TASK_REQUEST).toBeDefined()
    })

    it('contains replay events', () => {
      expect(SOCKET_EVENTS.REPLAY_STATUS).toBeDefined()
      expect(SOCKET_EVENTS.REPLAY_PROGRESS).toBeDefined()
      expect(SOCKET_EVENTS.REPLAY_LOADED).toBeDefined()
      expect(SOCKET_EVENTS.REPLAY_LOAD).toBeDefined()
      expect(SOCKET_EVENTS.REPLAY_ACTION).toBeDefined()
    })

    it('contains subscription events', () => {
      expect(SOCKET_EVENTS.SUBSCRIBE_TASK).toBeDefined()
      expect(SOCKET_EVENTS.UNSUBSCRIBE_TASK).toBeDefined()
    })
  })

  describe('APP_EVENTS', () => {
    it('is a non-empty object', () => {
      expect(typeof APP_EVENTS).toBe('object')
      expect(Object.keys(APP_EVENTS).length).toBeGreaterThan(0)
    })

    it('all values are strings', () => {
      Object.values(APP_EVENTS).forEach(v => {
        expect(typeof v).toBe('string')
      })
    })

    it('has no duplicate values', () => {
      const values = Object.values(APP_EVENTS)
      const unique = new Set(values)
      expect(unique.size).toBe(values.length)
    })

    it('all values start with "on"', () => {
      Object.values(APP_EVENTS).forEach(v => {
        expect(v.startsWith('on')).toBe(true)
      })
    })

    it('contains connection lifecycle events', () => {
      expect(APP_EVENTS.ON_CONNECTION_ESTABLISHED).toBeDefined()
      expect(APP_EVENTS.ON_DISCONNECT).toBeDefined()
      expect(APP_EVENTS.ON_RECONNECT).toBeDefined()
    })

    it('contains data stream events', () => {
      expect(APP_EVENTS.ON_DATA_STREAM).toBeDefined()
      expect(APP_EVENTS.ON_PROVIDER_UPDATE).toBeDefined()
    })
  })
})
