/**
 * Manages high-frequency streams.
 * Buffers large numbers of data points for visualizations such as scopes.
 */
export class StreamBuffer {
  /**
  * @param {number} maxSize Maximum number of data points kept in the buffer.
  *                         Acts as a hard cap to prevent unbounded growth.
  * @param {number} maxAgeMs Optional time window in milliseconds; data older
  *                          than `now - maxAgeMs` is dropped on each push.
  *                          Pass 0 to disable the time-based window.
   */
  constructor(maxSize = 60000, maxAgeMs = 0) {
    this.maxSize = maxSize;
    this.maxAgeMs = maxAgeMs;
    this.buffer = []; // Start with an empty, growable buffer
    this.lastValue = null;
    this.lastUncertainty = null;
    this.lastTimestamp = 0;
  }

  /**
  * Appends new data, concatenating incoming chunks with the existing buffer.
  * @param {Object} payload Data payload received from the server or provider.
   */
  push(payload) {
    const { value, values, timestamp, timestamps, distribution, startTime, endTime, uncertainty } = payload;
    let newPoints = [];
    const pointUncertainty = (uncertainty && typeof uncertainty === 'object') ? uncertainty : undefined;

    // Case 1: array or chunk processing for high-frequency streams.
    if (Array.isArray(values) && values.length > 0) {
      // A: linear distribution between start and end time.
      if (distribution === 'linear' && startTime && endTime) {
        const count = values.length;
        const dt = (endTime - startTime) / (count > 1 ? (count - 1) : 1);
        for (let i = 0; i < count; i++) {
          const t = startTime + (i * dt);
          const point = { t, v: values[i] };
          if (pointUncertainty) point.u = pointUncertainty;
          newPoints.push(point);
        }
      } 
      // B: discrete distribution with one timestamp per sample.
      else {
        const hasTimeArray = Array.isArray(timestamps) && timestamps.length === values.length;
        const baseTime = timestamp || Date.now();

        // Without explicit timestamps, keep the generated points monotonic so
        // rendering does not pile samples onto the same X position.
        let startTime = baseTime;
        if (!hasTimeArray && this.lastTimestamp && startTime <= this.lastTimestamp) {
          startTime = this.lastTimestamp + 1;
        }

        for (let i = 0; i < values.length; i++) {
          const t = hasTimeArray ? timestamps[i] : startTime + i;
          const point = { t, v: values[i] };
          if (pointUncertainty) point.u = pointUncertainty;
          newPoints.push(point);
        }
      }
      this.lastValue = values[values.length - 1];

    } 
    // Case 2: single-value payloads for legacy or low-speed streams.
    else if (value !== undefined) {
      const t = timestamp || Date.now();
      const point = { t, v: value };
      if (pointUncertainty) point.u = pointUncertainty;
      newPoints.push(point);
      this.lastValue = value;
    }

    if (newPoints.length > 0) {
        // Preserve time ordering by discarding points older than the last timestamp.
        if (this.lastTimestamp && newPoints[0].t <= this.lastTimestamp) {
            const firstValidIdx = newPoints.findIndex(p => p.t > this.lastTimestamp);
            if (firstValidIdx === -1) {
                // Every point is in the past, so nothing should be appended.
                return;
            }
            newPoints = newPoints.slice(firstValidIdx);
        }

        this.buffer = this.buffer.concat(newPoints);
        this.lastTimestamp = newPoints[newPoints.length - 1].t;
        this.lastUncertainty = newPoints[newPoints.length - 1].u || null;

        // Trim by age first (cheap when nothing to drop).
        if (this.maxAgeMs > 0) {
            const cutoff = this.lastTimestamp - this.maxAgeMs;
            // Find first index whose timestamp is > cutoff via binary search.
            let lo = 0, hi = this.buffer.length;
            while (lo < hi) {
                const mid = (lo + hi) >>> 1;
                if (this.buffer[mid].t < cutoff) lo = mid + 1; else hi = mid;
            }
            if (lo > 0) {
                this.buffer = this.buffer.slice(lo);
            }
        }

        // Trim the oldest data if the buffer grows beyond its capacity.
        const overflow = this.buffer.length - this.maxSize;
        if (overflow > 0) {
            this.buffer = this.buffer.slice(overflow);
        }
    }
  }

  /**
  * Returns the latest scalar value in O(1).
   */
  getLatest() {
    return this.lastValue;
  }

  /**
  * Returns the latest uncertainty object in O(1), if available.
   */
  getLatestUncertainty() {
    return this.lastUncertainty;
  }

  /**
  * Returns the full buffer in chronological order.
  * @returns {Array} Array of {t, v} objects.
   */
  getData() {
    return this.buffer;
  }

  /**
  * Binary search for timestamp lookup in O(log n).
   * @private
   */
  _binarySearchTimestamp(timestamp) {
    const data = this.getData();
    let left = 0;
    let right = data.length - 1;
    let result = -1;

    while (left <= right) {
      const mid = Math.floor((left + right) / 2);
      
      if (data[mid].t > timestamp) {
        result = mid;
        right = mid - 1;
      } else {
        left = mid + 1;
      }
    }

    return result;
  }

  /**
  * Returns only the data newer than the given timestamp.
   * @param {number} timestamp
   */
  getDataSince(timestamp) {
    if (this.buffer.length === 0 || timestamp >= this.lastTimestamp) {
        return [];
    }

    const data = this.getData();
    const idx = this._binarySearchTimestamp(timestamp);
    
    if (idx === -1) return [];
    return data.slice(idx);
  }

  /**
   * Leert den Buffer vollständig.
   */
  clear() {
    this.buffer = [];
    this.lastValue = null;
    this.lastUncertainty = null;
    this.lastTimestamp = 0;
  }

  /**
   * Gibt die anzahl der elemente im buffer zurück
   */
  length() {
    return this.buffer.length;
  }

  /**
   * Gibt das letzte element im buffer zurück
   */
  last() {
    return this.buffer.length > 0 ? this.buffer[this.buffer.length - 1] : null;
  }

  /**
   * Gibt das erste Element im Buffer zurück.
   */
  first() {
    return this.buffer.length > 0 ? this.buffer[0] : null;
  }

  /**
   * Gibt einen teil des buffers basierend auf einem zeitbereich zurück.
   * @param {number} startTime
   * @param {number} endTime
   */
  slice(startTime, endTime) {
    if (this.buffer.length === 0) {
      return [];
    }

    const startIndex = this._binarySearchTimestamp(startTime - 1);
    if (startIndex === -1) {
      return [];
    }

    let endIndex = this._binarySearchTimestamp(endTime);
    if (endIndex === -1) {
      endIndex = this.buffer.length;
    }

    return this.buffer.slice(startIndex, endIndex);
  }
}
