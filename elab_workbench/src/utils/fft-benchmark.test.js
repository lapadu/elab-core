import { describe, it, expect, beforeAll } from 'vitest';

/**
 * Performance Benchmark für WebGPU FFT vs. JavaScript
 * 
 * Benutze: npm test -- fft-benchmark.test.js
 * 
 * Warnung: Diese Tests sind *langsam* und führen viele Berechnungen durch.
 * Für Produktion in separate Bench-Suite verschieben.
 */

describe.skip('FFT Performance Benchmarks', () => {
  let processor;

  beforeAll(async () => {
    processor = null;
  });

  const generateTestSignal = (size) => {
    const signal = new Float32Array(size);
    // Multifrequency Signal: 1kHz + 5kHz + 12kHz @ 48kHz
    const sampleRate = 48000;
    for (let i = 0; i < size; i++) {
      const t = i / sampleRate;
      signal[i] =
        Math.sin(2 * Math.PI * 1000 * t) * 0.5 +
        Math.sin(2 * Math.PI * 5000 * t) * 0.3 +
        Math.sin(2 * Math.PI * 12000 * t) * 0.2;
    }
    return signal;
  };

  /**
   * Benchmark: 32k FFT
   * 
   * Expected:
   *   - WebGPU: 0.1-0.3 ms
   *   - JavaScript: 8-20 ms
   *   - Speedup: 40-100x
   */
  it.skip('benchmark 32k FFT (10 iterations)', async () => {
    const N = 32768;
    const signal = generateTestSignal(N);
    const iterations = 10;

    const startGPU = performance.now();
    for (let i = 0; i < iterations; i++) {
      await processor.computeFFT(signal);
    }
    const timeGPU = (performance.now() - startGPU) / iterations;

    const startJS = performance.now();
    for (let i = 0; i < iterations; i++) {
      processor.jsFFT(signal); // Direct JavaScript fallback
    }
    const timeJS = (performance.now() - startJS) / iterations;

    console.log(`\n32k FFT Benchmark:`);
    console.log(`  WebGPU:     ${timeGPU.toFixed(2)} ms`);
    console.log(`  JavaScript: ${timeJS.toFixed(2)} ms`);
    console.log(`  Speedup:    ${(timeJS / timeGPU).toFixed(1)}x`);

    expect(timeGPU).toBeLessThan(timeJS);
  });

  /**
   * Benchmark: 64k FFT
   * 
   * Expected:
   *   - WebGPU: 0.2-0.5 ms
   *   - JavaScript: 20-50 ms
   *   - Speedup: 50-150x
   */
  it.skip('benchmark 64k FFT (5 iterations)', async () => {
    const N = 65536;
    const signal = generateTestSignal(N);
    const iterations = 5;

    const startGPU = performance.now();
    for (let i = 0; i < iterations; i++) {
      await processor.computeFFT(signal);
    }
    const timeGPU = (performance.now() - startGPU) / iterations;

    const startJS = performance.now();
    for (let i = 0; i < iterations; i++) {
      processor.jsFFT(signal);
    }
    const timeJS = (performance.now() - startJS) / iterations;

    console.log(`\n64k FFT Benchmark:`);
    console.log(`  WebGPU:     ${timeGPU.toFixed(2)} ms`);
    console.log(`  JavaScript: ${timeJS.toFixed(2)} ms`);
    console.log(`  Speedup:    ${(timeJS / timeGPU).toFixed(1)}x`);

    expect(timeGPU).toBeLessThan(timeJS);
  });

  /**
   * Benchmark: 128k FFT
   * 
   * Expected:
   *   - WebGPU: 0.4-1.0 ms
   *   - JavaScript: 50-120 ms
   *   - Speedup: 80-200x
   */
  it.skip('benchmark 128k FFT (3 iterations)', async () => {
    const N = 131072;
    const signal = generateTestSignal(N);
    const iterations = 3;

    const startGPU = performance.now();
    for (let i = 0; i < iterations; i++) {
      await processor.computeFFT(signal);
    }
    const timeGPU = (performance.now() - startGPU) / iterations;

    const startJS = performance.now();
    for (let i = 0; i < iterations; i++) {
      processor.jsFFT(signal);
    }
    const timeJS = (performance.now() - startJS) / iterations;

    console.log(`\n128k FFT Benchmark:`);
    console.log(`  WebGPU:     ${timeGPU.toFixed(2)} ms`);
    console.log(`  JavaScript: ${timeJS.toFixed(2)} ms`);
    console.log(`  Speedup:    ${(timeJS / timeGPU).toFixed(1)}x`);

    expect(timeGPU).toBeLessThan(timeJS);
  });

  /**
   * Benchmark: Memory Transfer Overhead
   * 
   * Misst nur den Transfer zum/vom GPU-Speicher
   */
  it.skip('benchmark memory transfer overhead', async () => {
    const sizes = [32768, 65536, 131072];

    console.log('\nMemory Transfer Overhead:');
    console.log('Size      | Transfer Time');
    console.log('----------|---------------');

    for (const N of sizes) {
      const signal = generateTestSignal(N);
      const iterations = 20;

      const startTime = performance.now();
      for (let i = 0; i < iterations; i++) {
        // Nur Upload + Download, keine Berechnung
        const buffer = new Float32Array(N * 2);
        for (let j = 0; j < N; j++) {
          buffer[2 * j] = signal[j];
          buffer[2 * j + 1] = 0;
        }
      }
      const localTime = (performance.now() - startTime) / iterations;

      // GPU-Transfer (grobe Schätzung: PCIe Gen3 ~8 GB/s)
      const bytesPerFFT = N * 2 * 4; // 2 Complex * 4 bytes
      const estimatedGPUTransfer = bytesPerFFT / (8e9 / 1000); // ms

      console.log(
        `${N.toString().padEnd(9)} | ${localTime.toFixed(3)} ms (local) + ${estimatedGPUTransfer.toFixed(3)} ms (GPU est.)`
      );
    }
  });

  /**
   * Scaling Test: Wie skaliert Performance mit Fenster-Größe?
   */
  it.skip('scaling analysis', async () => {
    console.log('\nFFT Scaling Analysis (GPU):');
    console.log('Window   | Time    | Expected');
    console.log('---------|---------|----------');

    const sizes = [8192, 16384, 32768, 65536, 131072];

    for (const N of sizes) {
      const signal = generateTestSignal(N);

      const start = performance.now();
      await processor.computeFFT(signal);
      const time = performance.now() - start;

      // FFT is O(N log N)
      // Für 65536: O(65536 * log(65536)) = O(65536 * 16) ≈ 1M ops
      const expectedOps = N * Math.log2(N);

      console.log(
        `${(N / 1024).toFixed(0)}k       | ${time.toFixed(2)} ms | O(${expectedOps / 1e6 | 0}M)`
      );
    }
  });

  /**
   * Continuous Performance: Wie sieht die Performance unter Last aus?
   */
  it.skip('continuous performance under load', async () => {
    const N = 65536;
    const signal = generateTestSignal(N);
    const iterations = 50; // 50 FFTs in Folge

    console.log(`\nContinuous Performance (${N / 1024}k FFT, ${iterations} iterations):`);

    const times = [];
    for (let i = 0; i < iterations; i++) {
      const start = performance.now();
      await processor.computeFFT(signal);
      const time = performance.now() - start;
      times.push(time);
    }

    const avg = times.reduce((a, b) => a + b, 0) / times.length;
    const min = Math.min(...times);
    const max = Math.max(...times);
    const stdDev = Math.sqrt(
      times.reduce((sum, time) => sum + (time - avg) ** 2, 0) / times.length
    );

    console.log(`  Average:   ${avg.toFixed(3)} ms`);
    console.log(`  Min:       ${min.toFixed(3)} ms`);
    console.log(`  Max:       ${max.toFixed(3)} ms`);
    console.log(`  StdDev:    ${stdDev.toFixed(3)} ms`);
    console.log(`  Jitter:    ${((max - min) / avg * 100).toFixed(1)}%`);
  });
});
