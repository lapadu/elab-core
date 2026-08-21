/**
 * Pure pan/zoom math for the scope and spectrum canvases.
 *
 * Extracted from `useCanvasInteraction` so the geometry is unit-testable
 * without a DOM. The interaction hook still owns DOM events, debouncing,
 * and refs; it now delegates the actual viewport mutations here.
 *
 * All functions are pure: they take a viewport snapshot and return a new
 * snapshot. No mutation.
 */

/** @typedef {{ y_min: number, y_max: number }} ViewportY */
/** @typedef {ViewportY & { x_duration: number, x_offset: number }} ViewportDuration */
/** @typedef {ViewportY & { x_min: number, x_max: number }} ViewportRange */

const DEFAULT_ZOOM_FACTOR_OUT = 1.15
const DEFAULT_ZOOM_FACTOR_IN = 0.85

/**
 * Compute Y zoom around a normalized cursor (0 = bottom, 1 = top).
 * @param {ViewportY} vp
 * @param {number} cursorYNorm normalized [0, 1] – 1 = top of canvas
 * @param {number} factor      >1 = zoom out, <1 = zoom in
 * @returns {ViewportY}
 */
export function zoomY(vp, cursorYNorm, factor) {
    const range = vp.y_max - vp.y_min
    const newRange = range * factor
    const cursorVal = vp.y_min + cursorYNorm * range
    const y_min = cursorVal - cursorYNorm * newRange
    return { y_min, y_max: y_min + newRange }
}

/**
 * Compute X zoom in "duration" mode (scope).
 *
 * The visible window ends at `anchor - x_offset`, where the anchor itself may
 * scale with the duration (`anchor = base + anchorFraction * duration`). That is
 * the case while the view is trigger-aligned to the window centre
 * (anchorFraction 0.5); for the live/paused edge the anchor is fixed (0).
 * Both cases must be accounted for to keep the cursor's time value invariant.
 *
 * @param {ViewportDuration} vp
 * @param {number} cursorXNorm normalized [0, 1] – 0 = left
 * @param {number} factor
 * @param {(off: number, dur: number) => number} [clamp] optional offset clamp
 * @param {number} [anchorFraction=0] fraction of the duration the anchor moves by
 * @returns {{ x_duration: number, x_offset: number }}
 */
export function zoomXDuration(vp, cursorXNorm, factor, clamp, anchorFraction = 0) {
    const newDuration = vp.x_duration * factor
    const durationDelta = vp.x_duration - newDuration
    let newOffset = vp.x_offset + ((1 - cursorXNorm) - anchorFraction) * durationDelta
    if (clamp) {
        newOffset = clamp(newOffset, newDuration)
    } else {
        const maxHist = Math.max(newDuration * 10, 60000)
        newOffset = Math.max(-newDuration * 2, Math.min(maxHist, newOffset))
    }
    return { x_duration: newDuration, x_offset: newOffset }
}

/**
 * Compute X zoom in "range" mode (spectrum).
 * @param {ViewportRange} vp
 * @param {number} cursorXNorm
 * @param {number} factor
 * @param {(min: number, max: number) => { xMin: number, xMax: number }} [clamp]
 * @returns {{ x_min: number, x_max: number }}
 */
export function zoomXRange(vp, cursorXNorm, factor, clamp) {
    const span = Math.max(10, vp.x_max - vp.x_min)
    const newSpan = Math.max(10, span * factor)
    const cursorVal = vp.x_min + cursorXNorm * span
    let x_min = cursorVal - cursorXNorm * newSpan
    let x_max = x_min + newSpan
    if (clamp) {
        const c = clamp(x_min, x_max)
        x_min = c.xMin
        x_max = c.xMax
    }
    return { x_min, x_max }
}

/**
 * Compute pan deltas in pixel space and return the new viewport bounds.
 * @param {ViewportRange} snapshot the viewport at mouse-down time
 * @param {number} dx pixel delta in X
 * @param {number} dy pixel delta in Y
 * @param {number} canvasWidth
 * @param {number} canvasHeight
 * @returns {{ x_min: number, x_max: number, y_min: number, y_max: number }}
 */
export function panRange(snapshot, dx, dy, canvasWidth, canvasHeight) {
    const xSpan = snapshot.x_max - snapshot.x_min
    const ySpan = snapshot.y_max - snapshot.y_min
    const xUnitsPerPx = xSpan / Math.max(1, canvasWidth)
    const yUnitsPerPx = ySpan / Math.max(1, canvasHeight)
    return {
        x_min: snapshot.x_min - dx * xUnitsPerPx,
        x_max: snapshot.x_max - dx * xUnitsPerPx,
        y_min: snapshot.y_min + dy * yUnitsPerPx,
        y_max: snapshot.y_max + dy * yUnitsPerPx,
    }
}

/** Translate a wheel direction + modifier set into a zoom intent. */
export function wheelZoomIntent(deltaY, { altKey, shiftKey }) {
    const factor = deltaY > 0 ? DEFAULT_ZOOM_FACTOR_OUT : DEFAULT_ZOOM_FACTOR_IN
    const doYZoom = altKey || (!shiftKey && !altKey)
    const doXZoom = shiftKey || (!shiftKey && !altKey)
    return { factor, doXZoom, doYZoom }
}

/**
 * Search for a trigger event in a data array.
 *
 * @param {Array<{t: number, v: number}>} data  - Sorted time-series data points.
 * @param {string} mode   - 'rising', 'falling', or 'level'.
 * @param {number} level  - Trigger threshold level.
 * @param {number} [pretrigger=5] - Pretrigger percentage (0-100).
 * @returns {number|null} Interpolated timestamp of the trigger event, or null.
 */
export function findTrigger(data, mode, level, pretrigger = 5) {
    if (!data || data.length < 2) return null;

    const checkTrigger = (i) => {
        const p = data[i];
        const prev = data[i - 1];
        if (mode === 'rising' && prev.v < level && p.v >= level) {
            const fraction = (level - prev.v) / (p.v - prev.v);
            return prev.t + fraction * (p.t - prev.t);
        }
        if (mode === 'falling' && prev.v > level && p.v <= level) {
            const fraction = (level - prev.v) / (p.v - prev.v);
            return prev.t + fraction * (p.t - prev.t);
        }
        if (mode === 'level' && Math.abs(p.v - level) < 0.1) {
            return p.t;
        }
        return null;
    };

    const startIndex = Math.min(data.length - 1, Math.floor(data.length * (1 - pretrigger / 100)));
    // Search backward from start index
    for (let i = startIndex; i >= 1; i--) {
        const t = checkTrigger(i);
        if (t !== null) return t;
    }
    // Search forward from start index
    for (let i = startIndex + 1; i < data.length; i++) {
        const t = checkTrigger(i);
        if (t !== null) return t;
    }
    return null;
}
