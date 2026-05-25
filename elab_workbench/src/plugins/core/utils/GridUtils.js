/**
 * Shared grid and axis utility functions for canvas-based widgets.
 */

import { SYSTEM_COLORS } from "../../../utils/Shared.jsx";

export const NICE_NUMBERS = [1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10];

/**
 * Compute nice axis bounds for a given min/max range.
 */
export function calculateAxisBounds(min, max, ticks = 5) {
  if (min === max) {
    min -= 0.5;
    max += 0.5;
  }
  const range = max - min;
  if (range === 0 || !isFinite(range)) {
    return { min, max };
  }
  const roughTickSize = range / (ticks - 1);
  const exponent = Math.floor(Math.log10(roughTickSize));
  const powerOf10 = 10 ** exponent;
  const normalizedTickSize = roughTickSize / powerOf10;
  const niceTickSize = NICE_NUMBERS.find((n) => n >= normalizedTickSize);
  const finalTickSize = niceTickSize * powerOf10;
  const newMin = Math.floor(min / finalTickSize) * finalTickSize;
  const newMax = Math.ceil(max / finalTickSize) * finalTickSize;
  return { min: newMin, max: newMax };
}

/**
 * Choose a nice scale for a range expressed in a base unit.
 * @param {number} range      - The visible range in base units.
 * @param {Array}  tiers      - Array of { unit, divisor, maxRange? } sorted ascending by divisor.
 * @param {number} targetTicks - Desired number of ticks.
 * @returns {{ unit: string, divisor: number, niceStep: number }}
 */
export function chooseScale(range, tiers, targetTicks = 10) {
  let unit, divisor;
  for (const tier of tiers) {
    unit = tier.unit;
    divisor = tier.divisor;
    if (tier.maxRange !== undefined && range < tier.maxRange) break;
  }
  const rangeInUnit = range / divisor;
  const roughStep = rangeInUnit / targetTicks;
  if (roughStep <= 0 || !isFinite(roughStep)) return { unit, divisor, niceStep: 1 };
  const exponent = Math.floor(Math.log10(roughStep));
  const powerOf10 = 10 ** exponent;
  const normalized = roughStep / powerOf10;
  const niceNorm = NICE_NUMBERS.find((n) => n >= normalized) || 10;
  const niceStep = niceNorm * powerOf10;
  return { unit, divisor, niceStep };
}

/** Time-axis tiers (ms → display unit). */
export const TIME_TIERS = [
  { unit: 'µs', divisor: 0.001, maxRange: 1 },
  { unit: 'ms', divisor: 1,     maxRange: 1000 },
  { unit: 's',  divisor: 1000 },
];

/** Frequency-axis tiers (Hz → display unit). */
export const FREQ_TIERS = [
  { unit: 'Hz',  divisor: 1,    maxRange: 1e3 },
  { unit: 'kHz', divisor: 1e3,  maxRange: 1e6 },
  { unit: 'MHz', divisor: 1e6 },
];

/**
 * Format a tick label with the right number of decimals for the step size.
 */
export function formatTickLabel(value, niceStep) {
  if (niceStep >= 1) return value.toFixed(0);
  const decimals = Math.max(0, Math.ceil(-Math.log10(niceStep)));
  return value.toFixed(decimals);
}

/**
 * Draw horizontal and vertical grid lines with labels on a 2D canvas context.
 *
 * @param {CanvasRenderingContext2D} ctx
 * @param {number} W        - Logical canvas width
 * @param {number} H        - Logical canvas height
 * @param {object} xAxis    - { min, max, tiers, ticks?, labelY? }
 * @param {object} yAxis    - { min, max, ticks? }
 */
export function drawGrid(ctx, W, H, xAxis, yAxis) {
  ctx.strokeStyle = SYSTEM_COLORS.surface.subtle;
  ctx.lineWidth = 0.5;
  ctx.font = "10px monospace";
  ctx.fillStyle = SYSTEM_COLORS.text.secondary;
  ctx.beginPath();

  // X-axis grid
  const xRange = xAxis.max - xAxis.min;
  if (xRange > 0) {
    const { unit, divisor, niceStep } = chooseScale(xRange, xAxis.tiers, xAxis.ticks || 10);
    const startInUnit = xAxis.min / divisor;
    const endInUnit = xAxis.max / divisor;
    const firstTick = Math.ceil(startInUnit / niceStep) * niceStep;
    for (let tickVal = firstTick; tickVal <= endInUnit + niceStep * 0.001; tickVal += niceStep) {
      const val = tickVal * divisor;
      const x = W * ((val - xAxis.min) / xRange);
      if (x < 0 || x > W) continue;
      ctx.moveTo(x, 0);
      ctx.lineTo(x, H);
      const labelY = xAxis.labelY !== undefined ? xAxis.labelY : H - 5;
      if (x < W - 40) {
        ctx.fillText(`${formatTickLabel(tickVal, niceStep)}${unit}`, x + 3, labelY);
      }
    }
  }

  // Y-axis grid
  const yRange = yAxis.max - yAxis.min;
  const yTicks = yAxis.ticks || 6;
  if (yRange > 0) {
    for (let i = 0; i <= yTicks; i++) {
      const y = (H / yTicks) * i;
      ctx.moveTo(0, y);
      ctx.lineTo(W, y);
      const val = yAxis.max - (yRange / yTicks) * i;
      if (y > 10) {
        ctx.fillText(val.toFixed(2), 5, y - 2);
      }
    }
  }
  ctx.stroke();
}
