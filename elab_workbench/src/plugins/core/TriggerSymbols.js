/**
 * Trigger symbol drawing functions for the Scope canvas.
 * Each function draws a trigger marker at the given (x, y) position.
 *
 * Modes:
 *   rising  – white filled arrow pointing up
 *   falling – white filled arrow pointing down
 *   level   – white horizontal line
 */

import { SYSTEM_COLORS } from "../../utils/Shared.jsx";

const ARROW_SIZE = 12;
const LINE_HALF = 14;

function drawRising(ctx, x, y) {
    ctx.fillStyle = SYSTEM_COLORS.text.primary;
    ctx.beginPath();
    ctx.moveTo(x, y - ARROW_SIZE);
    ctx.lineTo(x - ARROW_SIZE / 2, y + ARROW_SIZE / 3);
    ctx.lineTo(x + ARROW_SIZE / 2, y + ARROW_SIZE / 3);
    ctx.closePath();
    ctx.fill();
}

function drawFalling(ctx, x, y) {
    ctx.fillStyle = SYSTEM_COLORS.text.primary;
    ctx.beginPath();
    ctx.moveTo(x, y + ARROW_SIZE);
    ctx.lineTo(x - ARROW_SIZE / 2, y - ARROW_SIZE / 3);
    ctx.lineTo(x + ARROW_SIZE / 2, y - ARROW_SIZE / 3);
    ctx.closePath();
    ctx.fill();
}

function drawLevel(ctx, x, y) {
    ctx.strokeStyle = SYSTEM_COLORS.text.primary;
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(x - LINE_HALF, y);
    ctx.lineTo(x + LINE_HALF, y);
    ctx.stroke();
}

export const TRIGGER_SYMBOLS = {
    rising: drawRising,
    falling: drawFalling,
    level: drawLevel,
};
