import { describe, it, expect } from 'vitest'
import { StreamBuffer } from './StreamingUtils.js'

describe('StreamBuffer – extended coverage', () => {
  describe('getDataSince()', () => {
    it('returns all data after given timestamp', () => {
      const b = new StreamBuffer()
      b.push({ value: 1, timestamp: 100 })
      b.push({ value: 2, timestamp: 200 })
      b.push({ value: 3, timestamp: 300 })
      b.push({ value: 4, timestamp: 400 })
      const result = b.getDataSince(200)
      expect(result).toEqual([
        { t: 300, v: 3 },
        { t: 400, v: 4 },
      ])
    })

    it('returns empty array for timestamp >= lastTimestamp', () => {
      const b = new StreamBuffer()
      b.push({ value: 1, timestamp: 100 })
      b.push({ value: 2, timestamp: 200 })
      expect(b.getDataSince(200)).toEqual([])
      expect(b.getDataSince(300)).toEqual([])
    })

    it('returns all data when timestamp < first element', () => {
      const b = new StreamBuffer()
      b.push({ value: 1, timestamp: 100 })
      b.push({ value: 2, timestamp: 200 })
      const result = b.getDataSince(50)
      expect(result).toEqual([
        { t: 100, v: 1 },
        { t: 200, v: 2 },
      ])
    })

    it('returns empty for empty buffer', () => {
      const b = new StreamBuffer()
      expect(b.getDataSince(100)).toEqual([])
    })

    it('handles exact timestamp boundary (exclusive)', () => {
      const b = new StreamBuffer()
      b.push({ value: 1, timestamp: 100 })
      b.push({ value: 2, timestamp: 200 })
      b.push({ value: 3, timestamp: 300 })
      // getDataSince(100) => points with t > 100
      const result = b.getDataSince(100)
      expect(result).toEqual([
        { t: 200, v: 2 },
        { t: 300, v: 3 },
      ])
    })
  })

  describe('slice(startTime, endTime)', () => {
    it('returns data within time range', () => {
      const b = new StreamBuffer()
      for (let i = 0; i < 10; i++) {
        b.push({ value: i, timestamp: 10000 + i * 100 })
      }
      // slice is inclusive of startTime and endTime
      const result = b.slice(10200, 10500)
      expect(result.length).toBe(4) // t=10200,10300,10400,10500
      expect(result[0]).toEqual({ t: 10200, v: 2 })
      expect(result[3]).toEqual({ t: 10500, v: 5 })
    })

    it('returns empty for range outside buffer', () => {
      const b = new StreamBuffer()
      b.push({ value: 1, timestamp: 100 })
      b.push({ value: 2, timestamp: 200 })
      expect(b.slice(500, 600)).toEqual([])
    })

    it('returns empty for empty buffer', () => {
      const b = new StreamBuffer()
      expect(b.slice(0, 100)).toEqual([])
    })

    it('returns all data for -Infinity to Infinity', () => {
      const b = new StreamBuffer()
      b.push({ value: 1, timestamp: 100 })
      b.push({ value: 2, timestamp: 200 })
      b.push({ value: 3, timestamp: 300 })
      const result = b.slice(-Infinity, Infinity)
      expect(result.length).toBe(3)
    })

    it('handles single-element slice', () => {
      const b = new StreamBuffer()
      b.push({ value: 1, timestamp: 100 })
      b.push({ value: 2, timestamp: 200 })
      b.push({ value: 3, timestamp: 300 })
      const result = b.slice(150, 250)
      expect(result.length).toBe(1)
      expect(result[0]).toEqual({ t: 200, v: 2 })
    })
  })

  describe('clear()', () => {
    it('removes all data and resets state', () => {
      const b = new StreamBuffer()
      b.push({ value: 42, timestamp: 1000 })
      b.push({ value: 43, timestamp: 1001 })
      b.clear()
      expect(b.getData()).toEqual([])
      expect(b.getLatest()).toBeNull()
      expect(b.length()).toBe(0)
    })

    it('allows pushing after clear', () => {
      const b = new StreamBuffer()
      b.push({ value: 1, timestamp: 100 })
      b.clear()
      b.push({ value: 2, timestamp: 50 }) // t=50, should work since lastTimestamp was reset
      expect(b.getData()).toEqual([{ t: 50, v: 2 }])
    })
  })

  describe('first() and last()', () => {
    it('first() returns the oldest point', () => {
      const b = new StreamBuffer()
      b.push({ value: 1, timestamp: 100 })
      b.push({ value: 2, timestamp: 200 })
      expect(b.first()).toEqual({ t: 100, v: 1 })
    })

    it('last() returns the newest point', () => {
      const b = new StreamBuffer()
      b.push({ value: 1, timestamp: 100 })
      b.push({ value: 2, timestamp: 200 })
      expect(b.last()).toEqual({ t: 200, v: 2 })
    })

    it('first() returns null for empty buffer', () => {
      expect(new StreamBuffer().first()).toBeNull()
    })

    it('last() returns null for empty buffer', () => {
      expect(new StreamBuffer().last()).toBeNull()
    })
  })

  describe('length()', () => {
    it('returns current buffer size', () => {
      const b = new StreamBuffer()
      expect(b.length()).toBe(0)
      b.push({ value: 1, timestamp: 100 })
      expect(b.length()).toBe(1)
      b.push({ value: 2, timestamp: 200 })
      expect(b.length()).toBe(2)
    })
  })

  describe('linear distribution (chunk payloads)', () => {
    it('distributes timestamps evenly for linear mode', () => {
      const b = new StreamBuffer()
      b.push({
        values: [0, 1, 2, 3, 4],
        distribution: 'linear',
        startTime: 5000,
        endTime: 5400,
      })
      const data = b.getData()
      expect(data.length).toBe(5)
      // dt = 400 / 4 = 100
      expect(data[0].t).toBe(5000)
      expect(data[1].t).toBe(5100)
      expect(data[2].t).toBe(5200)
      expect(data[3].t).toBe(5300)
      expect(data[4].t).toBe(5400)
    })

    it('handles single-value linear distribution', () => {
      const b = new StreamBuffer()
      b.push({
        values: [42],
        distribution: 'linear',
        startTime: 1000,
        endTime: 1000,
      })
      const data = b.getData()
      expect(data.length).toBe(1)
      expect(data[0]).toEqual({ t: 1000, v: 42 })
    })

    it('distributes high-frequency samples correctly', () => {
      const n = 1024
      const vals = Array.from({ length: n }, (_, i) => i)
      const b = new StreamBuffer()
      b.push({
        values: vals,
        distribution: 'linear',
        startTime: 10000,
        endTime: 11023,
      })
      const data = b.getData()
      expect(data.length).toBe(1024)
      expect(data[0].t).toBe(10000)
      expect(data[1023].t).toBe(11023)
    })
  })

  describe('discrete distribution (timestamps array)', () => {
    it('uses provided timestamps exactly', () => {
      const b = new StreamBuffer()
      b.push({
        values: [10, 20, 30],
        timestamps: [5, 15, 25],
      })
      const data = b.getData()
      expect(data).toEqual([
        { t: 5, v: 10 },
        { t: 15, v: 20 },
        { t: 25, v: 30 },
      ])
    })

    it('falls back to base timestamp for values without timestamps array', () => {
      const b = new StreamBuffer()
      b.push({
        values: [1, 2, 3],
        timestamp: 1000,
      })
      const data = b.getData()
      expect(data.length).toBe(3)
      // Without explicit timestamps: t = baseTime + index
      expect(data[0].t).toBe(1000)
      expect(data[1].t).toBe(1001)
      expect(data[2].t).toBe(1002)
    })

    it('ensures monotonic timestamps for repeated pushes without timestamp array', () => {
      const b = new StreamBuffer()
      b.push({ values: [1, 2, 3], timestamp: 100 })
      // Second push with same or earlier timestamp should adjust
      b.push({ values: [4, 5, 6], timestamp: 100 })
      const data = b.getData()
      expect(data.length).toBe(6)
      // All timestamps must be strictly increasing
      for (let i = 1; i < data.length; i++) {
        expect(data[i].t).toBeGreaterThan(data[i - 1].t)
      }
    })
  })

  describe('out-of-order handling', () => {
    it('drops entire chunk if all points are older than last timestamp', () => {
      const b = new StreamBuffer()
      b.push({ value: 1, timestamp: 1000 })
      b.push({
        values: [10, 20, 30],
        timestamps: [500, 600, 700],
      })
      // All are older than 1000, so nothing should be added
      expect(b.length()).toBe(1)
    })

    it('partially accepts chunk if some points are newer', () => {
      const b = new StreamBuffer()
      b.push({ value: 1, timestamp: 1000 })
      b.push({
        values: [10, 20, 30],
        timestamps: [900, 1000, 1100],
      })
      // Only t=1100 should be added (it's > lastTimestamp=1000)
      expect(b.length()).toBe(2)
      expect(b.last().t).toBe(1100)
    })
  })

  describe('maxSize cap with chunks', () => {
    it('caps buffer even with large chunk pushes', () => {
      const b = new StreamBuffer(10)
      const values = Array.from({ length: 100 }, (_, i) => i)
      const timestamps = Array.from({ length: 100 }, (_, i) => i * 10)
      b.push({ values, timestamps })
      expect(b.length()).toBe(10)
      // Should keep the last 10 points
      expect(b.last().t).toBe(990)
      expect(b.first().t).toBe(900)
    })
  })

  describe('maxAgeMs with chunks', () => {
    it('trims old data based on time window after chunk push', () => {
      const b = new StreamBuffer(1000, 50) // 50ms window
      b.push({
        values: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
        distribution: 'linear',
        startTime: 5000,
        endTime: 5090,
      })
      // lastTimestamp = 5090, cutoff = 5090 - 50 = 5040
      // Only points with t >= 5040 should remain
      const data = b.getData()
      expect(data.every(p => p.t >= 5040)).toBe(true)
    })
  })

  describe('_binarySearchTimestamp', () => {
    it('finds first index with timestamp > target', () => {
      const b = new StreamBuffer()
      b.push({ values: [1, 2, 3, 4, 5], timestamps: [100, 200, 300, 400, 500] })
      // Should find index where t > 250
      const idx = b._binarySearchTimestamp(250)
      expect(idx).toBe(2) // data[2].t = 300
    })

    it('returns -1 when all elements are <= target', () => {
      const b = new StreamBuffer()
      b.push({ values: [1, 2, 3], timestamps: [100, 200, 300] })
      expect(b._binarySearchTimestamp(300)).toBe(-1)
      expect(b._binarySearchTimestamp(500)).toBe(-1)
    })

    it('returns 0 when target is less than all elements', () => {
      const b = new StreamBuffer()
      b.push({ values: [1, 2, 3], timestamps: [100, 200, 300] })
      expect(b._binarySearchTimestamp(50)).toBe(0)
    })
  })
})
