import { describe, it, expect } from 'vitest'
import {
  calculateAxisBounds,
  chooseScale,
  formatTickLabel,
  NICE_NUMBERS,
  TIME_TIERS,
  FREQ_TIERS,
} from './GridUtils.js'

describe('GridUtils', () => {
  describe('calculateAxisBounds', () => {
    it('returns nice bounds for a normal range', () => {
      const b = calculateAxisBounds(0.3, 4.7, 5)
      expect(b.min).toBeLessThanOrEqual(0.3)
      expect(b.max).toBeGreaterThanOrEqual(4.7)
    })

    it('expands when min === max', () => {
      const b = calculateAxisBounds(3, 3, 5)
      expect(b.min).toBeLessThan(3)
      expect(b.max).toBeGreaterThan(3)
    })

    it('handles zero range gracefully', () => {
      const b = calculateAxisBounds(0, 0, 5)
      expect(b.min).toBe(-0.5)
      expect(b.max).toBe(0.5)
    })

    it('handles negative range', () => {
      const b = calculateAxisBounds(-10, -2, 5)
      expect(b.min).toBeLessThanOrEqual(-10)
      expect(b.max).toBeGreaterThanOrEqual(-2)
    })

    it('handles very small ranges (microvolts)', () => {
      const b = calculateAxisBounds(0.001, 0.005, 4)
      expect(b.min).toBeLessThanOrEqual(0.001)
      expect(b.max).toBeGreaterThanOrEqual(0.005)
    })

    it('returns input for non-finite range', () => {
      const b = calculateAxisBounds(0, Infinity, 5)
      expect(b.min).toBe(0)
      expect(b.max).toBe(Infinity)
    })
  })

  describe('chooseScale', () => {
    it('picks µs for sub-ms ranges', () => {
      const s = chooseScale(0.5, TIME_TIERS, 10)
      expect(s.unit).toBe('µs')
      expect(s.divisor).toBe(0.001)
    })

    it('picks ms for moderate ranges', () => {
      const s = chooseScale(500, TIME_TIERS, 10)
      expect(s.unit).toBe('ms')
      expect(s.divisor).toBe(1)
    })

    it('picks s for large time ranges', () => {
      const s = chooseScale(5000, TIME_TIERS, 10)
      expect(s.unit).toBe('s')
      expect(s.divisor).toBe(1000)
    })

    it('picks Hz for low frequency', () => {
      const s = chooseScale(500, FREQ_TIERS, 10)
      expect(s.unit).toBe('Hz')
    })

    it('picks kHz for mid frequency', () => {
      const s = chooseScale(50000, FREQ_TIERS, 10)
      expect(s.unit).toBe('kHz')
    })

    it('picks MHz for high frequency', () => {
      const s = chooseScale(5e6, FREQ_TIERS, 10)
      expect(s.unit).toBe('MHz')
    })

    it('returns niceStep > 0', () => {
      const s = chooseScale(100, TIME_TIERS, 10)
      expect(s.niceStep).toBeGreaterThan(0)
    })

    it('handles zero range gracefully', () => {
      const s = chooseScale(0, TIME_TIERS, 10)
      expect(s.niceStep).toBe(1) // fallback
    })
  })

  describe('formatTickLabel', () => {
    it('no decimals for step >= 1', () => {
      expect(formatTickLabel(5.0, 1)).toBe('5')
      expect(formatTickLabel(10.0, 2)).toBe('10')
    })

    it('one decimal for step 0.1-0.9', () => {
      expect(formatTickLabel(1.5, 0.5)).toBe('1.5')
    })

    it('two decimals for step 0.01-0.09', () => {
      expect(formatTickLabel(1.23, 0.01)).toBe('1.23')
    })

    it('three decimals for step 0.001', () => {
      expect(formatTickLabel(0.123, 0.001)).toBe('0.123')
    })
  })

  describe('NICE_NUMBERS', () => {
    it('is sorted ascending', () => {
      for (let i = 1; i < NICE_NUMBERS.length; i++) {
        expect(NICE_NUMBERS[i]).toBeGreaterThanOrEqual(NICE_NUMBERS[i - 1])
      }
    })

    it('starts with 1 and ends with 10', () => {
      expect(NICE_NUMBERS[0]).toBe(1)
      expect(NICE_NUMBERS[NICE_NUMBERS.length - 1]).toBe(10)
    })
  })
})
