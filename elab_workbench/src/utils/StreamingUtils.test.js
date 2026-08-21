import { describe, it, expect } from 'vitest'
import { StreamBuffer } from './StreamingUtils.js'

describe('StreamBuffer', () => {
  it('appends scalar pushes in order', () => {
    const b = new StreamBuffer()
    b.push({ value: 1, timestamp: 100 })
    b.push({ value: 2, timestamp: 101 })
    expect(b.getData()).toEqual([
      { t: 100, v: 1 },
      { t: 101, v: 2 },
    ])
    expect(b.getLatest()).toBe(2)
  })

  it('drops out-of-order pushes', () => {
    const b = new StreamBuffer()
    b.push({ value: 1, timestamp: 100 })
    b.push({ value: 99, timestamp: 50 }) // older - must be ignored
    expect(b.getData()).toEqual([{ t: 100, v: 1 }])
  })

  describe('zero and falsy timestamps', () => {
    it('treats timestamp 0 as a real timestamp, not as missing', () => {
      const b = new StreamBuffer()
      b.push({ value: 10, timestamp: 0 })
      b.push({ value: 11, timestamp: 50 })
      b.push({ value: 12, timestamp: 100 })
      expect(b.getData()).toEqual([
        { t: 0, v: 10 },
        { t: 50, v: 11 },
        { t: 100, v: 12 },
      ])
      expect(b.getLatest()).toBe(12)
    })

    it('expands a linear chunk that starts at t=0', () => {
      const b = new StreamBuffer()
      b.push({ values: [1, 2, 3], distribution: 'linear', startTime: 0, endTime: 20 })
      expect(b.getData()).toEqual([
        { t: 0, v: 1 },
        { t: 10, v: 2 },
        { t: 20, v: 3 },
      ])
    })

    it('keeps accepting samples after a clear', () => {
      const b = new StreamBuffer()
      b.push({ value: 1, timestamp: 5000 })
      b.clear()
      b.push({ value: 2, timestamp: 0 })
      b.push({ value: 3, timestamp: 50 })
      expect(b.getData()).toEqual([
        { t: 0, v: 2 },
        { t: 50, v: 3 },
      ])
    })
  })

  it('caps buffer at maxSize (rolling window)', () => {
    const b = new StreamBuffer(3)
    for (let i = 0; i < 10; i++) {
      b.push({ value: i, timestamp: 1000 + i })
    }
    const data = b.getData()
    expect(data.length).toBe(3)
    expect(data[data.length - 1]).toEqual({ t: 1009, v: 9 })
  })

  it('drops samples older than maxAgeMs', () => {
    const b = new StreamBuffer(1000, 100) // 100 ms window
    b.push({ value: 1, timestamp: 1000 })
    b.push({ value: 2, timestamp: 1050 })
    b.push({ value: 3, timestamp: 1200 })
    // After last push lastTimestamp = 1200, cutoff = 1100 -> only keep ts > 1100
    const data = b.getData()
    expect(data.map((p) => p.t)).toEqual([1200])
  })

  it('expands a linear-distribution chunk into individual points', () => {
    const b = new StreamBuffer()
    b.push({
      values: [10, 20, 30, 40, 50],
      distribution: 'linear',
      startTime: 1000,
      endTime: 1040,
    })
    const data = b.getData()
    expect(data.length).toBe(5)
    expect(data[0]).toEqual({ t: 1000, v: 10 })
    expect(data[4]).toEqual({ t: 1040, v: 50 })
  })

  it('honours an explicit timestamps array', () => {
    const b = new StreamBuffer()
    b.push({
      values: [1, 2, 3],
      timestamps: [10, 20, 30],
    })
    expect(b.getData().map((p) => p.t)).toEqual([10, 20, 30])
  })

  it('handles empty payloads safely', () => {
    const b = new StreamBuffer()
    b.push({})
    b.push({ values: [] })
    expect(b.getData()).toEqual([])
  })

  it('preserves uncertainty metadata and exposes latest uncertainty', () => {
    const b = new StreamBuffer()
    b.push({
      values: [10, 20],
      timestamps: [1000, 1010],
      uncertainty: { systematicAbs: 0.1, randomSigma: 0.2, confidenceK: 2 },
    })
    const data = b.getData()
    expect(data[0].u).toEqual({ systematicAbs: 0.1, randomSigma: 0.2, confidenceK: 2 })
    expect(data[1].u).toEqual({ systematicAbs: 0.1, randomSigma: 0.2, confidenceK: 2 })
    expect(b.getLatestUncertainty()).toEqual({ systematicAbs: 0.1, randomSigma: 0.2, confidenceK: 2 })
  })
})
