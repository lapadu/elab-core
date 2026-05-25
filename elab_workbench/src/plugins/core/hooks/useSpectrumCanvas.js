import { useEffect, useRef, useState, useCallback } from "react";
import { downsampleMinMax } from "../../../utils/downsampling";
import { fft, nextPow2 } from "../../../utils/fftProcessing";
import { calculateAxisBounds, drawGrid, FREQ_TIERS } from "../utils/GridUtils";
import { useCanvasInteraction, drawMeasurementOverlay } from "./useCanvasInteraction";
import WebGPUFFTProcessor from "../../../utils/webgpu-fft";

/** Threshold above which WebGPU acceleration is used (32k samples). */
const WEBGPU_FFT_THRESHOLD = 32768;

/** Shared WebGPU FFT processor instance (lazy-initialized). */
let gpuProcessor = null;
let gpuInitPromise = null;

function getGPUProcessor() {
  if (!gpuInitPromise) {
    gpuInitPromise = (async () => {
      const proc = new WebGPUFFTProcessor();
      const ok = await proc.init();
      if (ok) { gpuProcessor = proc; }
      return ok;
    })();
  }
  return gpuInitPromise;
}

/**
 * Compute the magnitude spectrum of the most recent N samples.
 * Returns { freqs: Float64Array, mags: Float64Array, binCount, sampleRateHz }.
 */
function computeSpectrum(data, fftSize) {
  const n = Math.min(data.length, fftSize);
  if (n < 4) return null;

  const totalTime = data[data.length - 1].t - data[data.length - n].t;
  if (totalTime <= 0) return null;
  const sampleRateHz = 1000 * (n - 1) / totalTime;

  const len = nextPow2(n);
  const re = new Float64Array(len);
  const im = new Float64Array(len);

  // Fill with the most recent n samples, apply Hann window.
  const offset = data.length - n;
  let mean = 0;
  for (let i = 0; i < n; i++) mean += data[offset + i].v;
  mean /= n;
  for (let i = 0; i < n; i++) {
    const w = 0.5 * (1 - Math.cos(2 * Math.PI * i / (n - 1)));
    re[i] = (data[offset + i].v - mean) * w;
  }

  fft(re, im, false);

  const binCount = len >>> 1;
  const freqs = new Float64Array(binCount);
  const mags = new Float64Array(binCount);
  const freqStep = sampleRateHz / len;

  for (let i = 0; i < binCount; i++) {
    freqs[i] = i * freqStep;
    mags[i] = Math.sqrt(re[i] * re[i] + im[i] * im[i]) / n * 2;
  }
  // DC bin should not be doubled.
  mags[0] /= 2;

  return { freqs, mags, binCount, sampleRateHz };
}

/**
 * Async FFT computation using WebGPU for large window sizes (>= 32k).
 * Falls back to JS-based computeSpectrum if WebGPU unavailable.
 */
async function computeSpectrumGPU(data, fftSize) {
  const n = Math.min(data.length, fftSize);
  if (n < 4) return null;

  const totalTime = data[data.length - 1].t - data[data.length - n].t;
  if (totalTime <= 0) return null;
  const sampleRateHz = 1000 * (n - 1) / totalTime;

  // Prepare windowed input
  const len = nextPow2(n);
  const offset = data.length - n;
  let mean = 0;
  for (let i = 0; i < n; i++) mean += data[offset + i].v;
  mean /= n;

  const input = new Float32Array(len);
  for (let i = 0; i < n; i++) {
    const w = 0.5 * (1 - Math.cos(2 * Math.PI * i / (n - 1)));
    input[i] = (data[offset + i].v - mean) * w;
  }

  // Use WebGPU processor if available
  if (!gpuProcessor) {
    // Fallback to JS if GPU not ready
    return computeSpectrum(data, fftSize);
  }

  const result = await gpuProcessor.computeFFT(input);

  const binCount = len >>> 1;
  const freqs = new Float64Array(binCount);
  const mags = new Float64Array(binCount);
  const freqStep = sampleRateHz / len;

  for (let i = 0; i < binCount; i++) {
    freqs[i] = i * freqStep;
    mags[i] = Math.sqrt(result.real[i] * result.real[i] + result.imag[i] * result.imag[i]) / n * 2;
  }
  mags[0] /= 2;

  return { freqs, mags, binCount, sampleRateHz };
}

/**
 * Canvas hook for rendering a frequency spectrum.
 */
export const useSpectrumCanvas = (
  canvasRef,
  sources,
  streamBuffers,
  task,
  uiSettings,
  setStats
) => {
  const initialMaxFreq = task.config?.maxFreq || 0;
  const detectedNyquist = useRef(1000);
  const hasAutoscaled = useRef(false);
  const lastRenderedData = useRef([]);
  const viewport = useRef({
    x_min: 0,
    x_max: initialMaxFreq || 1000,
    y_min: 0,
    y_max: 5,
  });
  const [renderTrigger, setRenderTrigger] = useState(0);

  const fftSize = task.config?.fftSize || 4096;
  const configMaxFreq = task.config?.maxFreq || 0;
  const configMaxFreqRef = useRef(configMaxFreq);

  // --- WebGPU async spectrum cache for large FFT sizes ---
  const gpuSpectraCache = useRef(new Map()); // channelId -> spectrum result
  const gpuComputeInFlight = useRef(false);
  const useGPU = fftSize >= WEBGPU_FFT_THRESHOLD;

  // Initialize GPU processor when large FFT is selected
  useEffect(() => {
    if (useGPU) { getGPUProcessor(); }
  }, [useGPU]);

  // Async GPU spectrum computation (runs outside rAF loop)
  useEffect(() => {
    if (!useGPU) return;
    let active = true;
    let timeoutId;

    const computeGPUSpectra = async () => {
      if (gpuComputeInFlight.current || !active) return;
      gpuComputeInFlight.current = true;

      try {
        for (const ch of sources) {
          if (!active) break;
          const buf = streamBuffers?.get(ch.id) || streamBuffers?.get(ch.originalId);
          if (!buf || buf.length() < 4) continue;
          const data = buf.slice(-Infinity, Infinity);
          const spec = await computeSpectrumGPU(data, fftSize);
          if (spec && active) {
            gpuSpectraCache.current.set(ch.id, spec);
          }
        }
        if (active) setRenderTrigger(c => c + 1);
      } finally {
        gpuComputeInFlight.current = false;
      }

      // Schedule next computation
      if (active) {
        timeoutId = setTimeout(computeGPUSpectra, 50); // ~20 updates/sec
      }
    };

    computeGPUSpectra();
    return () => {
      active = false;
      clearTimeout(timeoutId);
    };
  }, [useGPU, sources, streamBuffers, fftSize]);

  useEffect(() => {
    configMaxFreqRef.current = configMaxFreq;
  }, [configMaxFreq]);

  const onUpdate = useCallback(() => setRenderTrigger(c => c + 1), []);

  // Reset viewport when config changes.
  useEffect(() => {
    viewport.current.x_min = 0;
    viewport.current.y_min = 0;
    viewport.current.y_max = 5;
    viewport.current.x_max = configMaxFreq || detectedNyquist.current;
    hasAutoscaled.current = false;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setRenderTrigger(c => c + 1);
  }, [task.id, fftSize, configMaxFreq]);

  // Clamp helper for the interaction hook.
  const clampX = useCallback((minFreq, maxFreq) => {
    const availableMax = Math.max(10, configMaxFreqRef.current || detectedNyquist.current);
    const span = maxFreq - minFreq;
    if (span >= availableMax) return { xMin: 0, xMax: availableMax };
    let xMin = Math.max(0, minFreq);
    let xMax = xMin + span;
    if (xMax > availableMax) {
      xMax = availableMax;
      xMin = xMax - span;
    }
    return { xMin, xMax };
  }, []);

  const autoscaleOnce = useCallback((onlyY = false) => {
    let globalYMax = 0;
    let nyquist = 1000;
    let hasData = false;

    // Use current viewport x-axis if only scaling Y, otherwise check full data bounds for peak
    const minFreq = onlyY ? viewport.current.x_min : 0;
    const maxFreq = onlyY ? viewport.current.x_max : Infinity;

    sources.forEach(ch => {
      let spec;
      if (useGPU) {
        spec = gpuSpectraCache.current.get(ch.id);
      } else {
        const buf = streamBuffers?.get(ch.id) || streamBuffers?.get(ch.originalId);
        if (!buf || buf.length() < 4) return;
        const data = buf.slice(-Infinity, Infinity);
        spec = computeSpectrum(data, fftSize);
      }
      if (!spec) return;
      hasData = true;
      
      const currentNyquist = spec.sampleRateHz / 2;
      nyquist = Math.max(nyquist, currentNyquist);

      for (let i = 1; i < spec.binCount; i++) {
        if (spec.freqs[i] >= minFreq && spec.freqs[i] <= maxFreq && spec.mags[i] > globalYMax) {
          globalYMax = spec.mags[i];
        }
      }
    });

    if (hasData) {
      detectedNyquist.current = nyquist;
      
      if (!onlyY) {
        viewport.current.x_min = 0;
        viewport.current.x_max = configMaxFreqRef.current || nyquist;
      }

      const yMaxVal = globalYMax > 0 ? globalYMax : 5;
      const bounds = calculateAxisBounds(0, yMaxVal * 1.15, 4);
      viewport.current.y_min = 0; // Spectrum usually starts at 0
      viewport.current.y_max = Math.max(0.1, bounds.max);
      onUpdate();
    }
  }, [sources, streamBuffers, fftSize, useGPU, onUpdate]);

  const SNAP_RADIUS = 20;

  // Snap right-click cursor to nearest data point on spectrum
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
    return null;
  }, []);

  // Unified interaction hook — handles pan, zoom (wheel / alt+wheel).
  const interactionState = useCanvasInteraction(canvasRef, viewport, {
    xMode: "range",
    onUpdate,
    clampX,
    onDoubleClick: () => {
      autoscaleOnce(true); // only scale Y on double click
    },
    onRightDoubleClick: () => {
      // Reset x-axis to full frequency range
      viewport.current.x_min = 0;
      viewport.current.x_max = configMaxFreqRef.current || detectedNyquist.current;
      onUpdate();
    },
    snapToData,
    extraDeps: [sources, autoscaleOnce, snapToData],
  });

  // --- Render loop ---
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

      let minFreq = viewport.current.x_min;
      let maxFreq = viewport.current.x_max;
      const spectra = [];

      let hasValidData = false;

      // Compute spectrum for each source.
      sources.forEach(ch => {
        const buf = streamBuffers?.get(ch.id) || streamBuffers?.get(ch.originalId);
        if (!buf || buf.length() < 4) return;

        let spec;
        if (useGPU) {
          // Use cached GPU result for large FFT sizes
          spec = gpuSpectraCache.current.get(ch.id);
        } else {
          // Synchronous JS FFT for small sizes
          const data = buf.slice(-Infinity, Infinity);
          spec = computeSpectrum(data, fftSize);
        }
        if (!spec) return;
        spectra.push({ ch, spec });
        hasValidData = true;

        // Update detected Nyquist from actual sample rate.
        const nyquist = spec.sampleRateHz / 2;
        if (nyquist > detectedNyquist.current * 1.1 || spectra.length === 1) {
          detectedNyquist.current = nyquist;
        }
      });

      if (!hasAutoscaled.current && hasValidData) {
        hasAutoscaled.current = true;
        autoscaleOnce();
        // Read updated viewport values
        minFreq = viewport.current.x_min;
        maxFreq = viewport.current.x_max;
      }

      const xRange = Math.max(1e-9, maxFreq - minFreq);
      const yMin = viewport.current.y_min;
      const yMax = viewport.current.y_max;
      const yRange = yMax - yMin;

      // --- Grid ---
      drawGrid(ctx, W, H, {
        min: minFreq,
        max: maxFreq,
        tiers: FREQ_TIERS,
        ticks: 10,
      }, {
        min: yMin,
        max: yMax,
        ticks: 6,
      });

      // --- Draw spectra ---
      const newStats = {};
      const renderedEntries = [];
      spectra.forEach(({ ch, spec }) => {
        // Build {t,v} array for downsampling (reuse existing utility).
        const pts = [];
        for (let i = 1; i < spec.binCount; i++) {
          if (spec.freqs[i] < minFreq) continue;
          if (spec.freqs[i] > maxFreq) break;
          pts.push({ t: spec.freqs[i], v: spec.mags[i] });
        }
        if (pts.length < 2) return;

        const downsampled = downsampleMinMax(pts, W * 2);
        const color = ch.color || "#3b82f6";
        const pixelPoints = [];

        ctx.strokeStyle = color;
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        downsampled.forEach((p, i) => {
          const x = W * ((p.t - minFreq) / xRange);
          const y = H * (1 - (p.v - yMin) / yRange);
          pixelPoints.push({ px: x, py: y });
          if (i === 0) ctx.moveTo(x, y);
          else ctx.lineTo(x, y);
        });
        ctx.stroke();
        renderedEntries.push({ points: pixelPoints, color });

        // Peak detection for stats overlay.
        let peakFreq = 0, peakMag = 0;
        for (let i = 1; i < spec.binCount; i++) {
          if (spec.freqs[i] < minFreq) continue;
          if (spec.freqs[i] > maxFreq) break;
          if (spec.mags[i] > peakMag) {
            peakMag = spec.mags[i];
            peakFreq = spec.freqs[i];
          }
        }
        newStats[ch.id] = {
          peakFreq,
          peakMag,
          sampleRate: spec.sampleRateHz,
          resolution: spec.sampleRateHz / (spec.binCount * 2),
        };
      });
      lastRenderedData.current = renderedEntries;

      if (yRange > 0) {
        const getXValue = (xPx) => minFreq + (xPx / W) * xRange;
        const getYValue = (yPx) => yMax - (yPx / H) * yRange;
        const formatX = (val) => `f: ${val.toFixed(1)} Hz`;
        const formatY = (val) => `mag: ${val.toFixed(3)}`;
        drawMeasurementOverlay(ctx, W, H, interactionState.current, getXValue, getYValue, formatX, formatY);
      }
      
      setStats(newStats);
    };

    render();
    return () => {
      cancelAnimationFrame(animationFrameId);
    };
  }, [canvasRef, sources, streamBuffers, task, uiSettings, fftSize, setStats, renderTrigger, autoscaleOnce]);
};