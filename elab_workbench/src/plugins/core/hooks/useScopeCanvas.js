import { useEffect, useRef, useState, useCallback } from "react";
import { downsampleMinMax } from "../../../utils/downsampling";
import { calculateAxisBounds, drawGrid, TIME_TIERS } from "../utils/GridUtils";
import { useCanvasInteraction, drawMeasurementOverlay } from "./useCanvasInteraction";
import { TRIGGER_SYMBOLS } from "../TriggerSymbols";
import { SYSTEM_COLORS } from "../../../utils/Shared.jsx";

const uncertaintyHalfWidth = (uncertainty) => {
  if (!uncertainty || typeof uncertainty !== "object") return 0;
  const systematic = Number(uncertainty.systematicAbs);
  const randomSigma = Number(uncertainty.randomSigma);
  const confidenceK = Number(uncertainty.confidenceK);
  const k = Number.isFinite(confidenceK) ? Math.abs(confidenceK) : 2;
  const delta =
    (Number.isFinite(systematic) ? Math.abs(systematic) : 0) +
    (Number.isFinite(randomSigma) ? Math.abs(randomSigma) * k : 0);
  return Number.isFinite(delta) ? delta : 0;
};

const withAlpha = (hexColor, alpha) => {
  if (typeof hexColor !== "string" || !hexColor.startsWith("#")) {
    return `rgba(56, 189, 248, ${alpha})`;
  }
  const hex = hexColor.slice(1);
  if (hex.length !== 6) return `rgba(56, 189, 248, ${alpha})`;
  const parsed = Number.parseInt(hex, 16);
  if (!Number.isFinite(parsed)) return `rgba(56, 189, 248, ${alpha})`;
  const r = (parsed >> 16) & 255;
  const g = (parsed >> 8) & 255;
  const b = parsed & 255;
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
};

export const useScopeCanvas = (
  canvasRef,
  sources,
  streamBuffers,
  task,
  uiSettings,
  setStats,
  updateUiSetting,
  rawCaptureAwaiting = false,
  setRawCaptureAwaiting = null,
  onLeftDoubleClick = null,
) => {
  const viewport = useRef({
    x_duration: (task.config?.timeWindow || 10) * 1000,
    x_offset: 0,
    y_min: task.config?.yMin ?? -5,
    y_max: task.config?.yMax ?? 5,
  });

  const hasAutoscaled = useRef(false);
  const pausedAtTimestamp = useRef(null);
  const [renderTrigger, setRenderTrigger] = useState(0);
  // Tracks when data was last seen during RAW capture awaiting.
  // Auto-pause only triggers after a >2 s silence gap (provider disconnect/reconnect),
  // so leftover live-data frames in transit do not trigger a premature pause.
  const rawLastDataTime = useRef(0);
  const pausedData = useRef(null);
  const pausedTriggerInfo = useRef(null);
  const triggerPixelPos = useRef(null);
  const lastRenderedData = useRef([]);
  const lastRenderedTimestamp = useRef(0);
  const minBufferTimestamp = useRef(null);
  const maxBufferTimestamp = useRef(null);
  const anchorTimestamp = useRef(0);

  // Reset the silence tracker whenever a new RAW capture cycle starts.
  useEffect(() => {
    if (rawCaptureAwaiting) {
      rawLastDataTime.current = performance.now();
    }
  }, [rawCaptureAwaiting]);

  const onUpdate = useCallback(() => setRenderTrigger(c => c + 1), []);

  const clampDurationOffset = useCallback((desiredOffset, duration) => {
    const minT = minBufferTimestamp.current;
    const maxT = maxBufferTimestamp.current;
    const anchorT = anchorTimestamp.current;
    if (minT === null || maxT === null || !Number.isFinite(anchorT)) {
      return desiredOffset;
    }

    // Keep viewStart >= minT and viewEnd <= maxT.
    const minOffset = anchorT - maxT;
    const maxOffset = anchorT - duration - minT;
    if (maxOffset < minOffset) return minOffset;
    return Math.max(minOffset, Math.min(maxOffset, desiredOffset));
  }, []);

  // Reset the viewport entirely when the task itself changes.
  useEffect(() => {
    viewport.current.x_duration = (task.config?.timeWindow || 10) * 1000;
    viewport.current.y_min = task.config?.yMin ?? -5;
    viewport.current.y_max = task.config?.yMax ?? 5;
    viewport.current.x_offset = 0;
    hasAutoscaled.current = false;
    setRenderTrigger(c => c + 1);
    // Intentionally only re-run when task identity changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [task.id]);

  // Sync viewport with config panel changes without destroying transient interaction state.
  useEffect(() => {
    let changed = false;
    const newDur = (task.config?.timeWindow || 10) * 1000;
    if (Math.abs(viewport.current.x_duration - newDur) > 1) {
      viewport.current.x_duration = newDur;
      changed = true;
    }
    const newYMin = task.config?.yMin ?? -5;
    if (Math.abs(viewport.current.y_min - newYMin) > 0.001) {
      viewport.current.y_min = newYMin;
      changed = true;
    }
    const newYMax = task.config?.yMax ?? 5;
    if (Math.abs(viewport.current.y_max - newYMax) > 0.001) {
      viewport.current.y_max = newYMax;
      changed = true;
    }
    if (changed) {
      setRenderTrigger(c => c + 1);
    }
  }, [task.config?.timeWindow, task.config?.yMin, task.config?.yMax]);

  // Center viewport when a trigger is newly placed (same as right-double-click).
  const prevTrigger = useRef(task.config?.trigger ?? null);
  useEffect(() => {
    const cur = task.config?.trigger ?? null;
    if (!prevTrigger.current && cur) {
      // Center X (bring to live edge)
      viewport.current.x_offset = 0;
      // Center Y on trigger level
      const lvl = cur.level ?? 0;
      const halfRange = (viewport.current.y_max - viewport.current.y_min) / 2;
      viewport.current.y_min = lvl - halfRange;
      viewport.current.y_max = lvl + halfRange;
      setRenderTrigger(c => c + 1);
    }
    prevTrigger.current = cur;
  }, [task.config?.trigger]);

  const autoscaleOnce = useCallback(() => {
    let globalMin = Infinity, globalMax = -Infinity;
    const buffersToUse = uiSettings.isPaused ? pausedData.current : streamBuffers;
    const timestampToUse = uiSettings.isPaused
      ? (pausedAtTimestamp.current || lastRenderedTimestamp.current)
      : lastRenderedTimestamp.current;

    // When scaling only Y, only look at currently visible X range.
    // If we wanted to scale both, we might want to look at the whole buffer or a specific range.
    // For the Scope, even initial auto-fit currently just looks at the visible time window.
    const viewStartTime = timestampToUse - viewport.current.x_offset - viewport.current.x_duration;
    const viewEndTime = timestampToUse - viewport.current.x_offset;

    if (buffersToUse) {
      sources.forEach((ch) => {
        const buf = buffersToUse.get(ch.id) || buffersToUse.get(ch.originalId);
        if (buf) {
          const visibleData = buf.slice(viewStartTime, viewEndTime);
          visibleData.forEach(p => {
            if (p.v < globalMin) globalMin = p.v;
            if (p.v > globalMax) globalMax = p.v;
          });
        }
      });
    }

    if (globalMin !== Infinity && globalMax !== -Infinity) {
      let range = globalMax - globalMin;
      if (range === 0) {
          range = globalMax === 0 ? 2 : Math.abs(globalMax);
      }
      const pad = range * 0.1;
      const bounds = calculateAxisBounds(globalMin - pad, globalMax + pad, 4);
      viewport.current.y_min = bounds.min;
      viewport.current.y_max = bounds.max;
      updateUiSetting({ yMin: bounds.min, yMax: bounds.max });
    }
  }, [sources, streamBuffers, uiSettings.isPaused, updateUiSetting]);

  const TRIGGER_HIT_RADIUS = 20;
  const SNAP_RADIUS = 20;

  // Left-click hit-test: check if the click is near the trigger symbol
  const onLeftClickHitTest = useCallback((x, y) => {
    const tp = triggerPixelPos.current;
    if (!tp) return null;
    const dx = x - tp.x;
    const dy = y - tp.y;
    const dist = Math.sqrt(dx * dx + dy * dy);
    if (dist > TRIGGER_HIT_RADIUS) return null;

    // All trigger modes can be dragged vertically to adjust trigger level.
    return 'trigger-drag';
  }, []);

  const onLeftDoubleClickHitTest = useCallback((x, y) => {
    const tp = triggerPixelPos.current;
    const trig = task.config?.trigger;
    if (!tp || !trig) return false;

    const dx = x - tp.x;
    const dy = y - tp.y;
    const dist = Math.sqrt(dx * dx + dy * dy);
    if (dist > TRIGGER_HIT_RADIUS) return false;

    const nextMode = trig.mode === 'falling' ? 'rising' : 'falling';
    updateUiSetting({ trigger: { ...trig, mode: nextMode, level: 0 } });
    return true;
  }, [task.config?.trigger, updateUiSetting]);

  // Trigger drag: update trigger level as user drags
  const onTriggerDrag = useCallback((yVal) => {
    if (!task.config?.trigger) return;
    const trig = { ...task.config.trigger, level: Math.round(yVal * 1000) / 1000 };
    updateUiSetting({ trigger: trig });
  }, [task.config, updateUiSetting]);

  // Snap right-click cursor to nearest data point on chart
  const snapToData = useCallback((pixelX, pixelY) => {
    const entries = lastRenderedData.current;
    if (!entries || entries.length === 0) return null;

    let bestDist = Infinity;
    let bestPoint = null;

    for (const { points, color } of entries) {
      for (const p of points) {
        const dx = p.px - pixelX;
        const dy = p.py - pixelY;
        const dist = Math.sqrt(dx * dx + dy * dy);
        if (dist < bestDist) {
          bestDist = dist;
          bestPoint = { x: p.px, y: p.py, color };
        }
      }
    }
    if (bestDist <= SNAP_RADIUS) return bestPoint;

    // No real data point within radius — check if a line segment crosses the snap area.
    // Find the closest point on any segment (interpolated).
    let bestSegDist = Infinity;
    let bestSegPoint = null;

    for (const { points } of entries) {
      for (let i = 0; i < points.length - 1; i++) {
        const a = points[i];
        const b = points[i + 1];
        // Project (pixelX, pixelY) onto segment a→b
        const abx = b.px - a.px;
        const aby = b.py - a.py;
        const apx = pixelX - a.px;
        const apy = pixelY - a.py;
        const ab2 = abx * abx + aby * aby;
        if (ab2 === 0) continue;
        const t = Math.max(0, Math.min(1, (apx * abx + apy * aby) / ab2));
        const projX = a.px + t * abx;
        const projY = a.py + t * aby;
        const dx = pixelX - projX;
        const dy = pixelY - projY;
        const dist = Math.sqrt(dx * dx + dy * dy);
        if (dist < bestSegDist) {
          bestSegDist = dist;
          bestSegPoint = { x: projX, y: projY, color: SYSTEM_COLORS.state.warningStrong, interpolated: true };
        }
      }
    }
    if (bestSegDist <= SNAP_RADIUS) return bestSegPoint;
    return null;
  }, []);

  // Unified interaction hook — handles pan, zoom (wheel / alt+wheel / shift+wheel).
  const interactionState = useCanvasInteraction(canvasRef, viewport, {
    xMode: "duration",
    onUpdate,
    clampDurationOffset,
    onSettingsChange: (settings) => {
      updateUiSetting(settings);
    },
    onDoubleClick: () => {
      autoscaleOnce(true); // only scale Y on double click
      if (typeof onLeftDoubleClick === "function") {
        onLeftDoubleClick();
      }
    },
    onRightDoubleClick: () => {
      viewport.current.x_offset = 0;
      onUpdate();
    },
    onLeftClickHitTest,
    onLeftDoubleClickHitTest,
    onTriggerDrag,
    snapToData,
    extraDeps: [updateUiSetting, task.id, task.config, autoscaleOnce, onLeftClickHitTest, onLeftDoubleClickHitTest, onTriggerDrag, snapToData, onLeftDoubleClick],
  });

  // Render loop.
  useEffect(() => {
    let animationFrameId;
    const canvas = canvasRef.current;
    if (!canvas) return;

    const ctx = canvas.getContext("2d");
    const dpr = window.devicePixelRatio || 1;

    const render = () => {
      animationFrameId = requestAnimationFrame(render);
      const rect = canvas.getBoundingClientRect();
      if (rect.width === 0 || rect.height === 0) return;

      const W = rect.width;
      const H = rect.height;

      if (canvas.width !== W * dpr || canvas.height !== H * dpr) {
        canvas.width = W * dpr;
        canvas.height = H * dpr;
        ctx.scale(dpr, dpr);
      }
      ctx.clearRect(0, 0, W, H);

      // Latest timestamp across all sources (always track live for resume).
      let latestTimestamp = 0;
      sources.forEach((ch) => {
        const buf = streamBuffers?.get(ch.id) || streamBuffers?.get(ch.originalId);
        if (buf?.length() > 0) latestTimestamp = Math.max(latestTimestamp, buf.last().t);
      });
      if (latestTimestamp > 0) lastRenderedTimestamp.current = latestTimestamp;

      // Track absolute buffer bounds for panning clamp.
      // When paused, freeze bounds so clamping doesn't shift the view.
      if (!uiSettings.isPaused) {
        minBufferTimestamp.current = null;
        maxBufferTimestamp.current = null;
        sources.forEach((ch) => {
          const buf = streamBuffers?.get(ch.id) || streamBuffers?.get(ch.originalId);
          if (!buf || buf.length() === 0) return;
          const first = typeof buf.first === "function" ? buf.first() : null;
          const last = buf.last();
          if (first?.t !== undefined) {
            minBufferTimestamp.current = minBufferTimestamp.current === null
              ? first.t
              : Math.min(minBufferTimestamp.current, first.t);
          }
          if (last?.t !== undefined) {
            maxBufferTimestamp.current = maxBufferTimestamp.current === null
              ? last.t
              : Math.max(maxBufferTimestamp.current, last.t);
          }
        });
      }

      // --- RAW CAPTURE AUTO-PAUSE ---
      // Only trigger auto-pause after a silence gap of >2 s.
      // This ensures leftover live-data frames (still in transit when the
      // user clicked RAW Capture) are discarded, and only the actual RAW
      // data coming after the provider reconnect triggers the pause.
      if (rawCaptureAwaiting) {
        const hasData = sources.some(ch => {
          const buf = streamBuffers?.get(ch.id) || streamBuffers?.get(ch.originalId);
          return buf && buf.length() > 0;
        });
        if (hasData) {
          const now = performance.now();
          const gap = now - rawLastDataTime.current;
          if (gap > 2000) {
            // Data arrived after a long silence → this is RAW data.
            if (setRawCaptureAwaiting) setRawCaptureAwaiting(false);
            updateUiSetting({ isPaused: true });
          } else {
            // Data arrived too quickly → leftover live data, discard it.
            sources.forEach(ch => {
              const buf = streamBuffers?.get(ch.id) || streamBuffers?.get(ch.originalId);
              if (buf) buf.clear();
            });
          }
          rawLastDataTime.current = now;
        }
      }

      // --- PAUSE AND SNAPSHOT LOGIC ---
      if (uiSettings.isPaused && !pausedAtTimestamp.current) {
        pausedAtTimestamp.current = lastRenderedTimestamp.current;
        const snapshot = new Map();
        if (streamBuffers) {
          for (const [id, buffer] of streamBuffers.entries()) {
            const dataArray = buffer.slice(-Infinity, Infinity);
            snapshot.set(id, {
              slice: (start, end) => dataArray.filter(p => p.t >= start && p.t <= end),
              length: () => dataArray.length,
              last: () => dataArray.length > 0 ? dataArray[dataArray.length - 1] : { t: 0 },
            });
          }
        }
        pausedData.current = snapshot;
      } else if (!uiSettings.isPaused && pausedAtTimestamp.current) {
        pausedAtTimestamp.current = null;
        pausedData.current = null;
        pausedTriggerInfo.current = null;
      }

      const buffersToUse = uiSettings.isPaused ? pausedData.current : streamBuffers;
      let timestampToUse = uiSettings.isPaused
        ? (pausedAtTimestamp.current || lastRenderedTimestamp.current)
        : lastRenderedTimestamp.current;

      // --- Trigger Logic ---
      let triggerFoundT = null;
      let triggerMode = null;
      let triggerLevel = null;
      if (task.config?.trigger && buffersToUse) {
        if (uiSettings.isPaused) {
          // While paused, use the trigger info captured at pause time
          if (pausedTriggerInfo.current) {
            triggerFoundT = pausedTriggerInfo.current.triggerFoundT;
            triggerMode = pausedTriggerInfo.current.triggerMode;
            triggerLevel = pausedTriggerInfo.current.triggerLevel;
            if (triggerFoundT !== null) {
              timestampToUse = triggerFoundT + 0.5 * viewport.current.x_duration;
            }
          }
        } else {
        const trig = task.config.trigger;
        const triggerCh = sources.find(s => s.id === trig.channelId) || sources[0];
        if (triggerCh) {
          const triggerBuf = buffersToUse.get(triggerCh.id) || buffersToUse.get(triggerCh.originalId);
          if (triggerBuf) {
            // Search from (1 - pretrigger/100) into the buffer toward older values
            const data = triggerBuf.slice(-Infinity, Infinity);
            const mode = trig.mode || 'rising';
            const lvl = trig.level || 0;
            const pretrigger = trig.pretrigger ?? 5; // % — pre-trigger portion shown left of trigger
            triggerMode = mode;
            triggerLevel = lvl;

            const checkTrigger = (i) => {
                const p = data[i];
                const prev = data[i - 1];
                if (mode === 'rising' && prev.v < lvl && p.v >= lvl) {
                    const fraction = (lvl - prev.v) / (p.v - prev.v);
                    return prev.t + fraction * (p.t - prev.t);
                }
                if (mode === 'falling' && prev.v > lvl && p.v <= lvl) {
                    const fraction = (lvl - prev.v) / (p.v - prev.v);
                    return prev.t + fraction * (p.t - prev.t);
                }
                if (mode === 'level' && Math.abs(p.v - lvl) < 0.1) {
                    return p.t;
                }
                return null;
            };

            // Start at (1 - pretrigger%) of buffer and search backward toward older values
            const startIndex = Math.min(data.length - 1, Math.floor(data.length * (1 - pretrigger / 100)));
            for (let i = startIndex; i >= 1; i--) {
                const t = checkTrigger(i);
                if (t !== null) { triggerFoundT = t; break; }
            }
            // If not found backward, search forward from start index
            if (triggerFoundT === null) {
                for (let i = startIndex + 1; i < data.length; i++) {
                    const t = checkTrigger(i);
                    if (t !== null) { triggerFoundT = t; break; }
                }
            }

            if (triggerFoundT !== null) {
                // Always display trigger at 50% of the scope window; panning via x_offset shifts the view
                timestampToUse = triggerFoundT + 0.5 * viewport.current.x_duration;
            }
          }
        }
        // Store trigger info so it's available when pausing
        pausedTriggerInfo.current = { triggerFoundT, triggerMode, triggerLevel };
        }
      }

      anchorTimestamp.current = timestampToUse;
      viewport.current.x_offset = clampDurationOffset(viewport.current.x_offset, viewport.current.x_duration);
      timestampToUse = anchorTimestamp.current;

      if (!uiSettings.isPaused) pausedAtTimestamp.current = null;

      // Initial auto-scale if we have valid data and haven't done it yet
      if (!hasAutoscaled.current && latestTimestamp > 0) {
        let hasPoints = false;
        sources.forEach((ch) => {
            const buf = buffersToUse?.get(ch.id) || buffersToUse?.get(ch.originalId);
            if (buf && buf.length() > 0) hasPoints = true;
        });
        if (hasPoints) {
            hasAutoscaled.current = true;
            autoscaleOnce();
        }
      }

      const viewStartTime = timestampToUse - viewport.current.x_offset - viewport.current.x_duration;
      const viewEndTime = timestampToUse - viewport.current.x_offset;

      const yMin = viewport.current.y_min;
      const yMax = viewport.current.y_max;
      const yRange = yMax - yMin;

      // --- Grid ---
      drawGrid(ctx, W, H, {
        min: 0,
        max: viewport.current.x_duration,
        tiers: TIME_TIERS,
        ticks: 10,
        labelY: H - 5,
      }, {
        min: yMin,
        max: yMax,
        ticks: 8,
      });

      // Zero line.
      if (yMin < 0 && yMax > 0) {
        const zeroY = H - ((0 - yMin) / yRange) * H;
        ctx.strokeStyle = SYSTEM_COLORS.border.default;
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(0, zeroY);
        ctx.lineTo(W, zeroY);
        ctx.stroke();
      }

      // --- Draw trigger symbol (behind chart traces) ---
      if (triggerFoundT !== null && triggerMode) {
          const triggerX = W * ((triggerFoundT - viewStartTime) / viewport.current.x_duration);
          const triggerY = H * (1 - (triggerLevel - yMin) / yRange);

          // Store trigger pixel position for interaction hit-testing
          triggerPixelPos.current = (triggerX >= 0 && triggerX <= W)
            ? { x: triggerX, y: triggerY, mode: triggerMode, level: triggerLevel }
            : null;

          if (triggerX >= 0 && triggerX <= W) {
              ctx.save();
              // Vertical dashed indicator line
              ctx.strokeStyle = 'rgba(255, 255, 255, 0.25)';
              ctx.lineWidth = 1;
              ctx.setLineDash([4, 4]);
              ctx.beginPath();
              ctx.moveTo(triggerX, 0);
              ctx.lineTo(triggerX, H);
              ctx.stroke();
              ctx.setLineDash([]);
              ctx.restore();

              // Horizontal dashed level line
              if (triggerY >= 0 && triggerY <= H) {
                ctx.save();
                ctx.strokeStyle = 'rgba(255, 255, 255, 0.15)';
                ctx.lineWidth = 1;
                ctx.setLineDash([4, 4]);
                ctx.beginPath();
                ctx.moveTo(0, triggerY);
                ctx.lineTo(W, triggerY);
                ctx.stroke();
                ctx.setLineDash([]);
                ctx.restore();
              }

              // Mode-specific symbol
              const drawSymbol = TRIGGER_SYMBOLS[triggerMode];
              if (drawSymbol) drawSymbol(ctx, triggerX, triggerY);
          }
      } else if (triggerMode && triggerLevel !== null) {
          // Trigger configured but not found — still show level indicator at left edge
          const triggerY = H * (1 - (triggerLevel - yMin) / yRange);
          const triggerX = 20; // fixed position at left edge

          triggerPixelPos.current = (triggerY >= 0 && triggerY <= H)
            ? { x: triggerX, y: triggerY, mode: triggerMode, level: triggerLevel }
            : null;

          if (triggerY >= 0 && triggerY <= H) {
              ctx.save();
              // Horizontal dashed level line (dimmer to indicate not triggered)
              ctx.strokeStyle = 'rgba(234, 179, 8, 0.3)';
              ctx.lineWidth = 1;
              ctx.setLineDash([4, 4]);
              ctx.beginPath();
              ctx.moveTo(0, triggerY);
              ctx.lineTo(W, triggerY);
              ctx.stroke();
              ctx.setLineDash([]);
              ctx.restore();

              // Mode-specific symbol (dimmer)
              ctx.save();
              ctx.globalAlpha = 0.6;
              const drawSymbol = TRIGGER_SYMBOLS[triggerMode];
              if (drawSymbol) drawSymbol(ctx, triggerX, triggerY);
              ctx.restore();
          } else {
              triggerPixelPos.current = null;
          }
      } else {
          triggerPixelPos.current = null;
      }

      // --- Draw traces ---
      const renderedEntries = [];
      if (buffersToUse) {
        const newStats = {};
        sources.forEach((ch) => {
          const buf = buffersToUse.get(ch.id) || buffersToUse.get(ch.originalId);
          if (!buf) return;
          const visibleData = buf.slice(viewStartTime, viewEndTime);
          if (visibleData.length < 2) return;

          let sMin = Infinity, sMax = -Infinity;
          for (const p of visibleData) {
            if (p.v < sMin) sMin = p.v;
            if (p.v > sMax) sMax = p.v;
          }
          const last = visibleData[visibleData.length - 1];
          newStats[ch.id] = { current: last.v, min: sMin, max: sMax };

          const downsampled = downsampleMinMax(visibleData, W * 2);
          const color = ch.color || "#3b82f6";
          const pixelPoints = [];

          if (uiSettings?.showUncertaintyBand) {
            const upper = [];
            const lower = [];
            downsampled.forEach((p) => {
              const half = uncertaintyHalfWidth(p.u);
              if (!(half > 0)) return;
              const x = W * ((p.t - viewStartTime) / viewport.current.x_duration);
              upper.push({ x, y: H * (1 - (p.v + half - yMin) / yRange) });
              lower.push({ x, y: H * (1 - (p.v - half - yMin) / yRange) });
            });

            if (upper.length > 1 && lower.length > 1) {
              ctx.fillStyle = withAlpha(color, 0.14);
              ctx.beginPath();
              ctx.moveTo(upper[0].x, upper[0].y);
              for (let i = 1; i < upper.length; i++) ctx.lineTo(upper[i].x, upper[i].y);
              for (let i = lower.length - 1; i >= 0; i--) ctx.lineTo(lower[i].x, lower[i].y);
              ctx.closePath();
              ctx.fill();
            }
          }

          ctx.strokeStyle = color;
          ctx.lineWidth = 1.5;
          ctx.beginPath();
          downsampled.forEach((p, i) => {
            const x = W * ((p.t - viewStartTime) / viewport.current.x_duration);
            const y = H * (1 - (p.v - yMin) / yRange);
            pixelPoints.push({ px: x, py: y });
            if (i === 0) ctx.moveTo(x, y);
            else ctx.lineTo(x, y);
          });
          ctx.stroke();
          renderedEntries.push({ points: pixelPoints, color });
        });
        setStats(newStats);
      }
      lastRenderedData.current = renderedEntries;

      if (sources.length > 0 && yRange > 0) {
        const getXValue = (xPx) => (xPx / W) * viewport.current.x_duration;
        const getYValue = (yPx) => yMax - (yPx / H) * yRange;
        const formatX = (val) => `t: ${val.toFixed(1)} ms`;
        const formatY = (val) => `v: ${val.toFixed(3)} ${task.config?.unit || ""}`;
        drawMeasurementOverlay(ctx, W, H, interactionState.current, getXValue, getYValue, formatX, formatY);
      }
    };

    render();
    return () => {
      cancelAnimationFrame(animationFrameId);
    };
  }, [canvasRef, sources, streamBuffers, task, uiSettings, setStats, renderTrigger,
      updateUiSetting, rawCaptureAwaiting, setRawCaptureAwaiting, autoscaleOnce, clampDurationOffset, interactionState]);

  // Expose a function that centers the trigger in view (X=0 offset, Y centered on level).
  // Accepts optional yMin/yMax to use freshly computed values (avoids stale viewport state).
  const centerTriggerInView = useCallback((newYMin, newYMax) => {
    viewport.current.x_offset = 0;
    const trig = task.config?.trigger;
    if (trig) {
      const lvl = trig.level ?? 0;
      const yLo = newYMin ?? viewport.current.y_min;
      const yHi = newYMax ?? viewport.current.y_max;
      const halfRange = (yHi - yLo) / 2;
      viewport.current.y_min = lvl - halfRange;
      viewport.current.y_max = lvl + halfRange;
    } else {
      if (newYMin != null) viewport.current.y_min = newYMin;
      if (newYMax != null) viewport.current.y_max = newYMax;
    }
    setRenderTrigger(c => c + 1);
  }, [task.config?.trigger]);

  return { centerTriggerInView };
};
