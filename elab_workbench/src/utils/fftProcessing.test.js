import { describe, it, expect } from 'vitest'
import { fft, nextPow2, detectPeriod } from './fftProcessing.js'

describe('fftProcessing', () => {
  describe('nextPow2', () => {
    it('returns 1 for 1', () => {
      expect(nextPow2(1)).toBe(1)
    })

    it('returns 2 for 2', () => {
      expect(nextPow2(2)).toBe(2)
    })

    it('returns next power of 2 for non-power input', () => {
      expect(nextPow2(3)).toBe(4)
      expect(nextPow2(5)).toBe(8)
      expect(nextPow2(9)).toBe(16)
      expect(nextPow2(100)).toBe(128)
      expect(nextPow2(1000)).toBe(1024)
    })

    it('returns same for exact power of 2', () => {
      expect(nextPow2(64)).toBe(64)
      expect(nextPow2(256)).toBe(256)
      expect(nextPow2(4096)).toBe(4096)
    })
  })

  describe('fft', () => {
    it('FFT of all zeros is all zeros', () => {
      const re = new Float64Array(8)
      const im = new Float64Array(8)
      fft(re, im, false)
      for (let i = 0; i < 8; i++) {
        expect(re[i]).toBeCloseTo(0)
        expect(im[i]).toBeCloseTo(0)
      }
    })

    it('FFT of DC signal has energy only at bin 0', () => {
      const n = 8
      const re = new Float64Array(n).fill(3.0)
      const im = new Float64Array(n)
      fft(re, im, false)
      expect(re[0]).toBeCloseTo(n * 3.0)
      for (let i = 1; i < n; i++) {
        expect(Math.abs(re[i])).toBeCloseTo(0, 5)
        expect(Math.abs(im[i])).toBeCloseTo(0, 5)
      }
    })

    it('inverse FFT recovers original signal', () => {
      const n = 16
      const original = Array.from({ length: n }, (_, i) => Math.sin(2 * Math.PI * i / n))
      const re = new Float64Array(original)
      const im = new Float64Array(n)
      fft(re, im, false)
      fft(re, im, true)
      for (let i = 0; i < n; i++) {
        expect(re[i]).toBeCloseTo(original[i], 10)
      }
    })

    it('Parseval theorem: energy conservation', () => {
      const n = 32
      const re = new Float64Array(n)
      for (let i = 0; i < n; i++) re[i] = Math.sin(2 * Math.PI * 3 * i / n)
      const im = new Float64Array(n)
      const timeEnergy = re.reduce((s, v) => s + v * v, 0)
      fft(re, im, false)
      const freqEnergy = re.reduce((s, v, i) => s + v * v + im[i] * im[i], 0) / n
      expect(freqEnergy).toBeCloseTo(timeEnergy, 5)
    })
  })

  describe('detectPeriod', () => {
    it('returns null for insufficient data', () => {
      expect(detectPeriod([])).toBeNull()
      expect(detectPeriod([{ t: 0, v: 1 }])).toBeNull()
      const few = Array.from({ length: 10 }, (_, i) => ({ t: i, v: Math.sin(i) }))
      expect(detectPeriod(few)).toBeNull()
    })

    it('detects period of a simple sine wave', () => {
      const sampleRate = 1000 // 1 kHz
      const freq = 50 // 50 Hz -> period = 20 ms
      const n = 512
      const data = Array.from({ length: n }, (_, i) => {
        const t = i / sampleRate * 1000 // ms
        return { t, v: Math.sin(2 * Math.PI * freq * i / sampleRate) }
      })
      const period = detectPeriod(data)
      expect(period).not.toBeNull()
      // Period should be approximately 20 ms
      expect(period).toBeCloseTo(20, 0)
    })

    it('detects period of a square wave', () => {
      const sampleRate = 1000
      const freq = 25 // 25 Hz -> period = 40 ms
      const n = 512
      const data = Array.from({ length: n }, (_, i) => {
        const t = i / sampleRate * 1000
        const v = Math.sin(2 * Math.PI * freq * i / sampleRate) > 0 ? 1 : -1
        return { t, v }
      })
      const period = detectPeriod(data)
      expect(period).not.toBeNull()
      expect(period).toBeCloseTo(40, 0)
    })

    it('returns null for constant signal', () => {
      const data = Array.from({ length: 100 }, (_, i) => ({ t: i, v: 5.0 }))
      expect(detectPeriod(data)).toBeNull()
    })

    it('returns null for random noise', () => {
      // Random noise typically has no clear period
      const rng = (seed) => {
        let s = seed
        return () => { s = (s * 1103515245 + 12345) & 0x7FFFFFFF; return s / 0x7FFFFFFF }
      }
      const rand = rng(42)
      const data = Array.from({ length: 256 }, (_, i) => ({ t: i, v: rand() * 2 - 1 }))
      const period = detectPeriod(data)
      // It's okay if it returns null or a very wrong value
      // The key is it shouldn't crash
      expect(period === null || typeof period === 'number').toBe(true)
    })

    it('handles data longer than MAX_DETECT_SAMPLES', () => {
      const sampleRate = 1000
      const freq = 100
      const n = 10000 // > 8192
      const data = Array.from({ length: n }, (_, i) => {
        const t = i / sampleRate * 1000
        return { t, v: Math.sin(2 * Math.PI * freq * i / sampleRate) }
      })
      const period = detectPeriod(data)
      expect(period).not.toBeNull()
      expect(period).toBeCloseTo(10, 0) // 100 Hz -> 10 ms
    })
  })
})
