import { describe, it, expect } from 'vitest'
import { downsampleMinMax } from './downsampling.js'

describe('downsampleMinMax', () => {
  it('returns original data when threshold >= data length', () => {
    const data = [{ t: 0, v: 1 }, { t: 1, v: 2 }, { t: 2, v: 3 }]
    expect(downsampleMinMax(data, 3)).toBe(data)
    expect(downsampleMinMax(data, 10)).toBe(data)
  })

  it('returns original data for threshold <= 0', () => {
    const data = [{ t: 0, v: 1 }, { t: 1, v: 2 }]
    expect(downsampleMinMax(data, 0)).toBe(data)
    expect(downsampleMinMax(data, -5)).toBe(data)
  })

  it('reduces data to approximately threshold*2 points', () => {
    const data = Array.from({ length: 100 }, (_, i) => ({ t: i, v: Math.sin(i * 0.1) }))
    const result = downsampleMinMax(data, 10)
    // Each bucket produces 1-2 points, so max 20 points for threshold=10
    expect(result.length).toBeLessThanOrEqual(20)
    expect(result.length).toBeGreaterThan(0)
  })

  it('preserves min and max values in each bucket', () => {
    // Data with clear peaks: [0,5,0,5,0,5,...] alternating
    const data = Array.from({ length: 20 }, (_, i) => ({ t: i, v: i % 2 === 0 ? 0 : 5 }))
    const result = downsampleMinMax(data, 5)
    const values = result.map(p => p.v)
    expect(values).toContain(0)
    expect(values).toContain(5)
  })

  it('maintains chronological order within buckets', () => {
    const data = Array.from({ length: 50 }, (_, i) => ({ t: i * 10, v: Math.sin(i * 0.5) }))
    const result = downsampleMinMax(data, 5)
    for (let i = 1; i < result.length; i++) {
      expect(result[i].t).toBeGreaterThanOrEqual(result[i - 1].t)
    }
  })

  it('handles single-element buckets correctly', () => {
    const data = [{ t: 0, v: 1 }, { t: 1, v: 2 }]
    const result = downsampleMinMax(data, 1)
    // With bucketSize=2, should get min+max of the one bucket
    expect(result.length).toBeLessThanOrEqual(2)
  })

  it('collapses to single point when min equals max in bucket', () => {
    // All same value
    const data = Array.from({ length: 10 }, (_, i) => ({ t: i, v: 5 }))
    const result = downsampleMinMax(data, 2)
    // Each bucket has same min/max so only one point per bucket
    expect(result.length).toBe(2) // 2 buckets × 1 point
    expect(result[0].v).toBe(5)
  })

  it('handles large dataset efficiently', () => {
    const data = Array.from({ length: 100000 }, (_, i) => ({ t: i, v: Math.sin(i * 0.001) }))
    const start = performance.now()
    const result = downsampleMinMax(data, 1000)
    const elapsed = performance.now() - start
    expect(result.length).toBeLessThanOrEqual(2000)
    expect(elapsed).toBeLessThan(100) // Should be fast
  })
})
