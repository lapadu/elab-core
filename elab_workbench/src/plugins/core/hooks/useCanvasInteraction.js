import { useEffect, useRef } from "react";
import { SYSTEM_COLORS } from "../../../utils/Shared.jsx";
import { zoomXDuration } from "./canvasMath.js";

/** Minimum left-drag distance (px) before the view actually pans. */
const PAN_THRESHOLD_PX = 4;

/**
 * Reusable canvas interaction hook for pan and zoom.
 *
 * Works with any viewport ref that has at least { y_min, y_max }
 * plus one of two X-axis models:
 *   - "duration" mode (scope):  { x_duration, x_offset }
 *   - "range"    mode (spectrum): { x_min, x_max }
 *
 * @param {React.RefObject} canvasRef
 * @param {React.RefObject} viewport
 * @param {object} options
 * @param {"duration"|"range"} options.xMode
 * @param {function}           options.onUpdate        - Called after every viewport mutation.
 * @param {function}           [options.onDoubleClick]  - Custom double-click handler.
 * @param {function}           [options.onSettingsChange] - Debounced config sync (scope).
 * @param {function}           [options.clampX]         - (xMin, xMax) => {xMin, xMax} clamper for range mode.
 * @param {function}           [options.getXAnchorFraction] - Duration mode: fraction k of the
 *   window by which the time anchor itself moves when the duration changes
 *   (anchor = base + k * duration). 0 for a fixed edge anchor, 0.5 when the view
 *   is trigger-aligned to the window centre. Needed to keep wheel zoom pinned to
 *   the cursor.
 * @param {React.RefObject}    [options.autoscaleOverride] - Immediate autoscale override ref (scope).
 * @param {Array}              [options.extraDeps]       - Additional effect dependencies.
 */
export const useCanvasInteraction = (canvasRef, viewport, options) => {
  const {
    xMode,
    onUpdate,
    onDoubleClick,
    onSettingsChange,
    clampX,
    clampDurationOffset,
    getXAnchorFraction,
    onRightDoubleClick,
    onLeftClickHitTest,
    onLeftDoubleClickHitTest,
    onTriggerDrag,
    snapToData,
    extraDeps = [],
  } = options;

  const interactionState = useRef({ 
    isPanning: false, 
    panActive: false,
    snapshot: null,
    isRightDown: false,
    isTriggerDragging: false,
    hoverX: 0,
    hoverY: 0,
    rightDragStartX: 0,
    rightDragStartY: 0,
    isHovering: false,
    snappedStart: null,
    snappedPoint: null,
    pinnedMeasurement: null,
  });
  const debounceTimer = useRef(null);
  const lastRightDownTs = useRef(0);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    // ── helpers ──────────────────────────────────────────────
    const scheduleDebouncedUpdate = (settings) => {
      if (!onSettingsChange) return;
      if (debounceTimer.current) clearTimeout(debounceTimer.current);
      debounceTimer.current = setTimeout(() => onSettingsChange(settings), 150);
    };

    // ── WHEEL ───────────────────────────────────────────────
    const handleWheel = (e) => {
      if (interactionState.current.isPanning) return;
      e.preventDefault();

      const rect = canvas.getBoundingClientRect();
      const mouseX = e.clientX - rect.left;
      const mouseY = e.clientY - rect.top;
      const normalizedX = Math.max(0, Math.min(1, mouseX / rect.width));
      const normalizedY = 1 - Math.max(0, Math.min(1, mouseY / rect.height));

      // Scroll forward (deltaY > 0) = zoom out.
      const factor = e.deltaY > 0 ? 1.15 : 0.85;
      const altKey = e.altKey;
      const shiftKey = e.shiftKey;

      let xChanged = false;
      let yChanged = false;
      const settings = {};

      // ── Y zoom ────────────────────────────────────────────
      // Zoom Y if Alt is pressed, OR if no modifier is pressed.
      const doYZoom = altKey || (!shiftKey && !altKey);
      if (doYZoom) {
        const curYRange = viewport.current.y_max - viewport.current.y_min;
        const newYRange = curYRange * factor;
        const mouseYVal = viewport.current.y_min + normalizedY * curYRange;
        viewport.current.y_min = mouseYVal - normalizedY * newYRange;
        viewport.current.y_max = viewport.current.y_min + newYRange;

        yChanged = true;
        if (xMode === "duration") {
          settings.yMin = viewport.current.y_min;
          settings.yMax = viewport.current.y_max;
        }
      }

      // ── X zoom ────────────────────────────────────────────
      // Zoom X if Shift is pressed, OR if no modifier is pressed.
      const doXZoom = shiftKey || (!shiftKey && !altKey);
      if (doXZoom) {
        if (xMode === "duration") {
          // viewEnd = anchorBase + k*duration - offset, so the offset correction
          // that pins the cursor depends on how far the anchor itself moves.
          const anchorK = getXAnchorFraction ? getXAnchorFraction() : 0;
          const zoomed = zoomXDuration(
            viewport.current,
            normalizedX,
            factor,
            clampDurationOffset,
            anchorK,
          );
          viewport.current.x_duration = zoomed.x_duration;
          viewport.current.x_offset = zoomed.x_offset;
          settings.timeWindow = zoomed.x_duration / 1000;

          xChanged = true;
        } else {
          // Range mode (spectrum).
          const oldMin = viewport.current.x_min;
          const oldMax = viewport.current.x_max;
          const oldSpan = Math.max(10, oldMax - oldMin);
          const newSpan = Math.max(10, oldSpan * factor);
          const cursorVal = oldMin + normalizedX * oldSpan;
          let newMin = cursorVal - normalizedX * newSpan;
          let newMax = newMin + newSpan;
          if (clampX) {
            const c = clampX(newMin, newMax);
            newMin = c.xMin;
            newMax = c.xMax;
          }
          viewport.current.x_min = newMin;
          viewport.current.x_max = newMax;
          xChanged = true;
        }
      }

      if (xChanged || yChanged) {
        if (Object.keys(settings).length) scheduleDebouncedUpdate(settings);
        onUpdate();
      }
    };

    // ── MOUSE DOWN ──────────────────────────────────────────
    const handleMouseDown = (e) => {
      // Clear the last frozen measurement on the next *left* click.
      if (e.button === 0 && interactionState.current.pinnedMeasurement) {
        interactionState.current.pinnedMeasurement = null;
        onUpdate();
      }

      if (e.button === 0) {
        e.preventDefault();
        const rect = canvas.getBoundingClientRect();
        const x = e.clientX - rect.left;
        const y = e.clientY - rect.top;
        // Check if click hits a trigger symbol (or other interactive element)
        if (onLeftClickHitTest) {
          const result = onLeftClickHitTest(x, y);
          if (result === 'trigger-drag') {
            interactionState.current.isTriggerDragging = true;
            canvas.style.cursor = "ns-resize";
            return;
          }
          if (result === 'handled') return;
        }
        interactionState.current.isPanning = true;
        interactionState.current.panActive = false;
        interactionState.current.snapshot = {
          x_duration: viewport.current.x_duration,
          x_offset: viewport.current.x_offset,
          x_min: viewport.current.x_min,
          x_max: viewport.current.x_max,
          y_min: viewport.current.y_min,
          y_max: viewport.current.y_max,
          startX: e.clientX,
          startY: e.clientY,
        };
        canvas.style.cursor = "grabbing";
      } else if (e.button === 2) {
        e.preventDefault();
        const now = Date.now();
        if (onRightDoubleClick && now - lastRightDownTs.current < 400) {
          onRightDoubleClick();
          lastRightDownTs.current = 0;
          return;
        }
        lastRightDownTs.current = now;

        const rect = canvas.getBoundingClientRect();
        const rx = e.clientX - rect.left;
        const ry = e.clientY - rect.top;
        interactionState.current.isRightDown = true;
        canvas.style.cursor = "crosshair";
        interactionState.current.hoverX = rx;
        interactionState.current.hoverY = ry;
        // Snap start to nearest data point
        if (snapToData) {
          const snapped = snapToData(rx, ry);
          interactionState.current.snappedStart = snapped;
          interactionState.current.snappedPoint = snapped;
          interactionState.current.rightDragStartX = snapped ? snapped.x : rx;
          interactionState.current.rightDragStartY = snapped ? snapped.y : ry;
        } else {
          interactionState.current.snappedStart = null;
          interactionState.current.snappedPoint = null;
          interactionState.current.rightDragStartX = rx;
          interactionState.current.rightDragStartY = ry;
        }
        onUpdate();
      }
    };

    // ── MOUSE MOVE ──────────────────────────────────────────
    const handleMouseMove = (e) => {
      const rect = canvas.getBoundingClientRect();
      const x = e.clientX - rect.left;
      const y = e.clientY - rect.top;
      
      interactionState.current.hoverX = x;
      interactionState.current.hoverY = y;
      
      const isOverCanvas = 
        e.clientX >= rect.left && e.clientX <= rect.right &&
        e.clientY >= rect.top && e.clientY <= rect.bottom;
      interactionState.current.isHovering = isOverCanvas;

      // Handle trigger level dragging
      if (interactionState.current.isTriggerDragging) {
        e.preventDefault();
        if (onTriggerDrag) {
          const normalizedY = 1 - Math.max(0, Math.min(1, y / rect.height));
          const yVal = viewport.current.y_min + normalizedY * (viewport.current.y_max - viewport.current.y_min);
          onTriggerDrag(yVal);
        }
        onUpdate();
        return;
      }

      // Snap to nearest data point for right-click overlay
      if (interactionState.current.isRightDown && snapToData) {
        const snapped = snapToData(x, y);
        interactionState.current.snappedPoint = snapped;
        onUpdate();
      }

      if (!interactionState.current.isPanning) return;
      e.preventDefault();
      const snap = interactionState.current.snapshot;
      const dx = e.clientX - snap.startX;
      const dy = e.clientY - snap.startY;

      // Ignore sub-threshold movement so the jitter between the two clicks of a
      // double-click cannot pan the view.
      if (!interactionState.current.panActive) {
        if (Math.hypot(dx, dy) < PAN_THRESHOLD_PX) return;
        interactionState.current.panActive = true;
      }

      if (xMode === "duration") {
        const timePerPx = snap.x_duration / rect.width;
        let newOff = snap.x_offset + dx * timePerPx;
        if (clampDurationOffset) {
          newOff = clampDurationOffset(newOff, snap.x_duration);
        } else {
          const maxHist = Math.max(snap.x_duration * 10, 60000);
          newOff = Math.max(-snap.x_duration * 2, Math.min(maxHist, newOff));
        }
        viewport.current.x_offset = newOff;

        const yRange = snap.y_max - snap.y_min;
        const yShift = dy * (yRange / rect.height);
        viewport.current.y_min = snap.y_min + yShift;
        viewport.current.y_max = snap.y_max + yShift;
      } else {
        const span = Math.max(10, snap.x_max - snap.x_min);
        const shift = dx * (span / rect.width);
        let newMin = snap.x_min - shift;
        let newMax = snap.x_max - shift;
        if (clampX) {
          const c = clampX(newMin, newMax);
          newMin = c.xMin;
          newMax = c.xMax;
        }
        viewport.current.x_min = newMin;
        viewport.current.x_max = newMax;

        const yRange = snap.y_max - snap.y_min;
        const yShift = dy * (yRange / rect.height);
        viewport.current.y_min = snap.y_min + yShift;
        viewport.current.y_max = snap.y_max + yShift;
      }
      onUpdate();
    };

    // ── MOUSE UP ────────────────────────────────────────────
    const handleMouseUp = (e) => {
      if (e.button === 0) {
        if (interactionState.current.isTriggerDragging) {
          interactionState.current.isTriggerDragging = false;
          canvas.style.cursor = "default";
        } else if (interactionState.current.isPanning) {
          interactionState.current.isPanning = false;
          interactionState.current.panActive = false;
          interactionState.current.snapshot = null;
          canvas.style.cursor = "default";
        }
      } else if (e.button === 2 && interactionState.current.isRightDown) {
        const rect = canvas.getBoundingClientRect();
        const curX = interactionState.current.snappedPoint
          ? interactionState.current.snappedPoint.x
          : Math.max(0, Math.min(rect.width, interactionState.current.hoverX));
        const curY = interactionState.current.snappedPoint
          ? interactionState.current.snappedPoint.y
          : Math.max(0, Math.min(rect.height, interactionState.current.hoverY));

        interactionState.current.pinnedMeasurement = {
          rightDragStartX: interactionState.current.rightDragStartX,
          rightDragStartY: interactionState.current.rightDragStartY,
          snappedStart: interactionState.current.snappedStart,
          snappedPoint: interactionState.current.snappedPoint,
          hoverX: curX,
          hoverY: curY,
        };
        interactionState.current.isRightDown = false;
        interactionState.current.snappedStart = null;
        interactionState.current.snappedPoint = null;
        canvas.style.cursor = "default";
        onUpdate();
      }
    };

    // ── DOUBLE CLICK ────────────────────────────────────────
    const handleDoubleClick = (e) => {
      if (onLeftDoubleClickHitTest) {
        const rect = canvas.getBoundingClientRect();
        const x = e.clientX - rect.left;
        const y = e.clientY - rect.top;
        if (onLeftDoubleClickHitTest(x, y)) {
          return;
        }
      }
      if (onDoubleClick) onDoubleClick();
    };

    // ── CONTEXT MENU ────────────────────
    const handleContextMenu = (e) => {
      e.preventDefault(); // Disable default context menu
    };

    // ── Register ────────────────────────────────────────────
    canvas.addEventListener("mousedown", handleMouseDown);
    window.addEventListener("mousemove", handleMouseMove);
    window.addEventListener("mouseup", handleMouseUp);
    canvas.addEventListener("wheel", handleWheel, { passive: false });
    canvas.addEventListener("dblclick", handleDoubleClick);
    canvas.addEventListener("contextmenu", handleContextMenu);
    canvas.style.cursor = "default";

    return () => {
      canvas.removeEventListener("mousedown", handleMouseDown);
      window.removeEventListener("mousemove", handleMouseMove);
      window.removeEventListener("mouseup", handleMouseUp);
      canvas.removeEventListener("wheel", handleWheel);
      canvas.removeEventListener("dblclick", handleDoubleClick);
      canvas.removeEventListener("contextmenu", handleContextMenu);
      if (debounceTimer.current) clearTimeout(debounceTimer.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [canvasRef, ...extraDeps]);

  return interactionState;
};

export function drawMeasurementOverlay(ctx, W, H, interactionState, getXValue, getYValue, formatX, formatY) {
  const activeMeasurement = interactionState.isRightDown
    ? interactionState
    : interactionState.pinnedMeasurement;
  if (!activeMeasurement) return;

  const { rightDragStartX, rightDragStartY, snappedStart, snappedPoint } = activeMeasurement;

  // Use snapped position if available, otherwise use raw hover position
  const curX = snappedPoint
    ? Math.max(0, Math.min(W, snappedPoint.x))
    : Math.max(0, Math.min(W, activeMeasurement.hoverX));
  const curY = snappedPoint
    ? Math.max(0, Math.min(H, snappedPoint.y))
    : Math.max(0, Math.min(H, activeMeasurement.hoverY));
  const curValX = getXValue(curX);
  const curValY = getYValue(curY);

  // Start position (locked to snapped start if available)
  const startX = Math.max(0, Math.min(W, rightDragStartX));
  const startY = Math.max(0, Math.min(H, rightDragStartY));

  ctx.save();

  // If dragging (dist > a few pixels), draw the box
  const dx = curX - startX;
  const dy = curY - startY;
  const isDragging = Math.abs(dx) > 3 || Math.abs(dy) > 3;

  const LINE_H = 16;
  const FONT = "12px monospace";

  function drawMultiLabel(x, y, lines, bgColor) {
    ctx.font = FONT;
    const pad = 6;
    let maxW = 0;
    for (const line of lines) {
      const tw = ctx.measureText(line).width;
      if (tw > maxW) maxW = tw;
    }
    const boxW = maxW + pad * 2;
    const boxH = LINE_H * lines.length + pad;

    let boxX = x + 10;
    let boxY = y + 10;

    if (boxX + boxW > W) boxX = x - boxW - 10;
    if (boxY + boxH > H) boxY = y - boxH - 10;

    boxX = Math.max(0, Math.min(W - boxW, boxX));
    boxY = Math.max(0, Math.min(H - boxH, boxY));

    ctx.fillStyle = bgColor;
    ctx.fillRect(boxX, boxY, boxW, boxH);
    ctx.strokeStyle = "rgba(148, 163, 184, 0.7)";
    ctx.strokeRect(boxX, boxY, boxW, boxH);
    ctx.fillStyle = SYSTEM_COLORS.text.primary;
    lines.forEach((line, i) => {
      ctx.fillText(line, boxX + pad, boxY + pad + LINE_H * i + 11);
    });
  }

  function drawSnapDot(px, py, point) {
    if (!point) return;
    ctx.fillStyle = point.color || SYSTEM_COLORS.text.primary;
    ctx.beginPath();
    ctx.arc(px, py, 4, 0, Math.PI * 2);
    ctx.fill();
  }

  if (isDragging) {
    const startValX = getXValue(startX);
    const startValY = getYValue(startY);

    // Draw frame
    ctx.strokeStyle = "rgba(255, 255, 255, 0.4)";
    ctx.lineWidth = 1;
    ctx.setLineDash([4, 4]);
    ctx.strokeRect(startX, startY, curX - startX, curY - startY);
    ctx.setLineDash([]);
    ctx.fillStyle = "rgba(255, 255, 255, 0.05)";
    ctx.fillRect(startX, startY, curX - startX, curY - startY);

    // Crosshairs at current
    ctx.strokeStyle = "rgba(255, 255, 255, 0.2)";
    ctx.beginPath();
    ctx.moveTo(curX, 0); ctx.lineTo(curX, H);
    ctx.moveTo(0, curY); ctx.lineTo(W, curY);
    ctx.stroke();

    // Compute deltas
    const diffX = curValX - startValX;
    const diffY = curValY - startValY;

    // Start label (single line)
    drawMultiLabel(startX, startY, [
      `${formatX(startValX)}  ${formatY(startValY)}`
    ], "rgba(15, 23, 42, 0.8)");

    // Current label (multi-line: value, delta, frequency)
    const curLines = [
      `${formatX(curValX)}  ${formatY(curValY)}`,
      `Δ ${formatX(diffX)}  Δ ${formatY(diffY)}`,
    ];
    // Show resulting frequency if x-axis delta represents time
    if (Math.abs(diffX) > 0.001) {
      const freqHz = 1000 / Math.abs(diffX);
      curLines.push(freqHz >= 1000 ? `f: ${(freqHz / 1000).toFixed(3)} kHz` : `f: ${freqHz.toFixed(2)} Hz`);
    }
    drawMultiLabel(curX, curY, curLines, "rgba(15, 23, 42, 0.9)");

    // Snap indicators
    drawSnapDot(startX, startY, snappedStart);
    drawSnapDot(curX, curY, snappedPoint);

  } else {
    // Just right clicked, show crosshair and current pos
    ctx.strokeStyle = "rgba(255, 255, 255, 0.2)";
    ctx.lineWidth = 1;
    ctx.setLineDash([3, 3]);
    ctx.beginPath();
    ctx.moveTo(curX, 0); ctx.lineTo(curX, H);
    ctx.moveTo(0, curY); ctx.lineTo(W, curY);
    ctx.stroke();
    ctx.setLineDash([]);

    drawSnapDot(curX, curY, snappedPoint);
    drawMultiLabel(curX, curY, [
      `${formatX(curValX)}  ${formatY(curValY)}`
    ], "rgba(15, 23, 42, 0.9)");
  }

  ctx.restore();
}
