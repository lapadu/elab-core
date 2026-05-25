import { describe, it, expect } from 'vitest'
import {
    zoomY,
    zoomXDuration,
    zoomXRange,
    panRange,
    wheelZoomIntent,
    findTrigger,
} from './canvasMath.js'

describe('zoomY', () => {
    it('zooms out around the cursor', () => {
        const r = zoomY({ y_min: 0, y_max: 10 }, 0.5, 2)
        expect(r.y_min).toBeCloseTo(-5)
        expect(r.y_max).toBeCloseTo(15)
    })

    it('keeps cursor value invariant when zooming in', () => {
        const vp = { y_min: 0, y_max: 100 }
        const cursor = 0.25 // value 25
        const r = zoomY(vp, cursor, 0.5)
        const cursorAfter = r.y_min + cursor * (r.y_max - r.y_min)
        expect(cursorAfter).toBeCloseTo(25)
    })
})

describe('zoomXDuration', () => {
    it('shrinks duration when zooming in', () => {
        const r = zoomXDuration({ x_duration: 1000, x_offset: 0, y_min: 0, y_max: 1 }, 0.5, 0.5)
        expect(r.x_duration).toBeCloseTo(500)
    })

    it('uses caller-provided clamp', () => {
        const clamp = (off) => Math.max(0, off)
        const r = zoomXDuration(
            { x_duration: 1000, x_offset: 0, y_min: 0, y_max: 1 },
            1,   // cursor at right edge would push offset negative
            2,
            clamp,
        )
        expect(r.x_offset).toBeGreaterThanOrEqual(0)
    })
})

describe('zoomXRange', () => {
    it('keeps cursor value invariant', () => {
        const vp = { x_min: 0, x_max: 1000, y_min: 0, y_max: 1 }
        const cursor = 0.3
        const cursorVal = vp.x_min + cursor * (vp.x_max - vp.x_min) // 300
        const r = zoomXRange(vp, cursor, 0.5)
        const cursorAfter = r.x_min + cursor * (r.x_max - r.x_min)
        expect(cursorAfter).toBeCloseTo(cursorVal)
    })

    it('clamps to caller-supplied bounds', () => {
        const clamp = (xMin, xMax) => ({ xMin: Math.max(0, xMin), xMax: Math.min(1000, xMax) })
        const r = zoomXRange(
            { x_min: 0, x_max: 1000, y_min: 0, y_max: 1 },
            0.0,
            2.0,
            clamp,
        )
        expect(r.x_min).toBeGreaterThanOrEqual(0)
        expect(r.x_max).toBeLessThanOrEqual(1000)
    })

    it('refuses to collapse span below minimum', () => {
        const vp = { x_min: 0, x_max: 5, y_min: 0, y_max: 1 } // span < 10
        const r = zoomXRange(vp, 0.5, 0.0001)
        expect(r.x_max - r.x_min).toBeGreaterThanOrEqual(10)
    })
})

describe('panRange', () => {
    it('translates by pixel deltas', () => {
        const snap = { x_min: 0, x_max: 100, y_min: 0, y_max: 100 }
        const r = panRange(snap, 10, 0, 100, 100)
        expect(r.x_min).toBeCloseTo(-10)
        expect(r.x_max).toBeCloseTo(90)
        expect(r.y_min).toBeCloseTo(0)
    })
})

describe('wheelZoomIntent', () => {
    it('default: zoom both axes out on positive deltaY', () => {
        const i = wheelZoomIntent(120, { altKey: false, shiftKey: false })
        expect(i.factor).toBeGreaterThan(1)
        expect(i.doXZoom).toBe(true)
        expect(i.doYZoom).toBe(true)
    })

    it('shift restricts to X', () => {
        const i = wheelZoomIntent(-120, { altKey: false, shiftKey: true })
        expect(i.factor).toBeLessThan(1)
        expect(i.doXZoom).toBe(true)
        expect(i.doYZoom).toBe(false)
    })

    it('alt restricts to Y', () => {
        const i = wheelZoomIntent(120, { altKey: true, shiftKey: false })
        expect(i.doXZoom).toBe(false)
        expect(i.doYZoom).toBe(true)
    })
})

describe('findTrigger', () => {
    // Helper: generate a sine wave data array
    const sineData = (n, freq, offset = 0) =>
        Array.from({ length: n }, (_, i) => ({
            t: i * 10,
            v: offset + Math.sin((2 * Math.PI * freq * i) / n),
        }))

    // Helper: generate a pulse signal (0V to 5V square)
    const pulseData = (n, period) =>
        Array.from({ length: n }, (_, i) => ({
            t: i * 10,
            v: (i % period) < period / 2 ? 0 : 5,
        }))

    it('detects rising edge crossing level', () => {
        const data = sineData(100, 2) // 2 cycles, crosses 0
        const t = findTrigger(data, 'rising', 0)
        expect(t).not.toBeNull()
        // The trigger time should be between two sample timestamps
        expect(t).toBeGreaterThan(0)
    })

    it('detects falling edge crossing level', () => {
        const data = sineData(100, 2)
        const t = findTrigger(data, 'falling', 0)
        expect(t).not.toBeNull()
        expect(t).toBeGreaterThan(0)
    })

    it('returns null when pulse never crosses trigger level 0', () => {
        // Pulse from 0V to 5V — never crosses a level of -1V
        const data = pulseData(100, 20)
        const t = findTrigger(data, 'rising', -1)
        expect(t).toBeNull()
    })

    it('returns null when signal stays above trigger level (no crossing)', () => {
        // Pulse 0→5V, trigger at 0V: rising means prev < 0 && curr >= 0
        // Since min is 0, prev is never < 0
        const data = pulseData(100, 20)
        const t = findTrigger(data, 'rising', 0)
        expect(t).toBeNull()
    })

    it('detects rising edge at mid-level for pulse signal', () => {
        // Pulse 0→5V, trigger at 2.5V: prev < 2.5 (0) and curr >= 2.5 (5)
        const data = pulseData(100, 20)
        const t = findTrigger(data, 'rising', 2.5)
        expect(t).not.toBeNull()
    })

    it('interpolates trigger time between samples', () => {
        // Simple ramp crossing: 0V at t=0, 10V at t=100
        const data = [
            { t: 0, v: 0 },
            { t: 100, v: 10 },
        ]
        const t = findTrigger(data, 'rising', 5)
        // Should interpolate to t=50
        expect(t).toBeCloseTo(50)
    })

    it('detects level trigger within tolerance', () => {
        const data = [
            { t: 0, v: 0 },
            { t: 10, v: 2.95 },
            { t: 20, v: 3.0 },
            { t: 30, v: 3.5 },
        ]
        const t = findTrigger(data, 'level', 3.0)
        expect(t).toBe(20)
    })

    it('returns null for empty or single-point data', () => {
        expect(findTrigger([], 'rising', 0)).toBeNull()
        expect(findTrigger([{ t: 0, v: 1 }], 'rising', 0)).toBeNull()
        expect(findTrigger(null, 'rising', 0)).toBeNull()
    })

    it('respects pretrigger percentage for search start', () => {
        // 10 points, rising crosses at index 2 (early) and index 8 (late)
        const data = [
            { t: 0, v: -1 }, { t: 10, v: -1 },
            { t: 20, v: 1 },  // crossing at i=2
            { t: 30, v: 1 },  { t: 40, v: 1 },
            { t: 50, v: 1 },  { t: 60, v: 1 },
            { t: 70, v: -1 }, { t: 80, v: -1 },
            { t: 90, v: 1 },  // crossing at i=9
        ]
        // With pretrigger=5%, search starts near end (index 9), finds late crossing
        const tLate = findTrigger(data, 'rising', 0, 5)
        // With pretrigger=80%, search starts near beginning (index 2)
        const tEarly = findTrigger(data, 'rising', 0, 80)
        expect(tLate).not.toBeNull()
        expect(tEarly).not.toBeNull()
        // The late trigger should be at a later time
        expect(tLate).toBeGreaterThan(tEarly)
    })
})
