/**
 * In-place radix-2 Cooley-Tukey FFT.
 * @param {Float64Array} re - Real parts (length must be power of 2).
 * @param {Float64Array} im - Imaginary parts (same length).
 * @param {boolean} invert - true for inverse FFT.
 */
export function fft(re, im, invert = false) {
    const n = re.length;
    for (let i = 1, j = 0; i < n; i++) {
        let bit = n >> 1;
        for (; j & bit; bit >>= 1) j ^= bit;
        j ^= bit;
        if (i < j) {
            let tmp = re[i]; re[i] = re[j]; re[j] = tmp;
            tmp = im[i]; im[i] = im[j]; im[j] = tmp;
        }
    }
    for (let len = 2; len <= n; len *= 2) {
        const ang = 2 * Math.PI / len * (invert ? -1 : 1);
        const wRe = Math.cos(ang), wIm = Math.sin(ang);
        for (let i = 0; i < n; i += len) {
            let curRe = 1, curIm = 0;
            const half = len >> 1;
            for (let j = 0; j < half; j++) {
                const k = i + j + half;
                const vRe = re[k] * curRe - im[k] * curIm;
                const vIm = re[k] * curIm + im[k] * curRe;
                re[k] = re[i + j] - vRe;
                im[k] = im[i + j] - vIm;
                re[i + j] += vRe;
                im[i + j] += vIm;
                const newRe = curRe * wRe - curIm * wIm;
                curIm = curRe * wIm + curIm * wRe;
                curRe = newRe;
            }
        }
    }
    if (invert) {
        for (let i = 0; i < n; i++) { re[i] /= n; im[i] /= n; }
    }
}

/** Smallest power of 2 >= v. */
export function nextPow2(v) { let p = 1; while (p < v) p <<= 1; return p; }

/** Max samples used for period detection (power of 2). */
const MAX_DETECT_SAMPLES = 8192;

/**
 * Detects the fundamental period of a periodic signal using FFT-based
 * autocorrelation (Wiener-Khinchin theorem). O(n log n).
 * @param {Array<{t: number, v: number}>} data - Time series data with timestamps in ms.
 * @returns {number|null} Detected period in ms, or null if no periodicity found.
 */
export function detectPeriod(data) {
    if (data.length < 20) return null;

    const window = data.length > MAX_DETECT_SAMPLES
        ? data.slice(data.length - MAX_DETECT_SAMPLES)
        : data;
    const n = window.length;

    const totalTime = window[n - 1].t - window[0].t;
    if (totalTime <= 0) return null;
    const avgInterval = totalTime / (n - 1);

    let mean = 0;
    for (let i = 0; i < n; i++) mean += window[i].v;
    mean /= n;

    const fftLen = nextPow2(n * 2);
    const re = new Float64Array(fftLen);
    const im = new Float64Array(fftLen);
    for (let i = 0; i < n; i++) re[i] = window[i].v - mean;

    fft(re, im, false);
    for (let i = 0; i < fftLen; i++) {
        re[i] = re[i] * re[i] + im[i] * im[i];
        im[i] = 0;
    }
    fft(re, im, true);

    const r0 = re[0];
    if (r0 === 0) return null;

    const maxLag = Math.floor(n / 2);
    let zeroCross = 1;
    while (zeroCross < maxLag && re[zeroCross] / r0 > 0) zeroCross++;
    if (zeroCross >= maxLag) return null;

    for (let lag = zeroCross; lag < maxLag - 1; lag++) {
        if (re[lag] >= re[lag - 1] &&
            re[lag] >= re[lag + 1] &&
            re[lag] / r0 > 0.2) {
            return lag * avgInterval;
        }
    }

    return null;
}
