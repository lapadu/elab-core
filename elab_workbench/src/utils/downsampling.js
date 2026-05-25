/**
 * Downsamples time-series data using a min-max approach for each bucket.
 * This is a fast algorithm that preserves the visual peaks of the data.
 *
 * @param {Array<{t: number, v: number}>} data The input data array.
 * @param {number} threshold The number of points to downsample to.
 * @returns {Array<{t: number, v: number}>} The downsampled data.
 */
export function downsampleMinMax(data, threshold) {
    if (threshold >= data.length || threshold <= 0) {
        return data;
    }

    const bucketSize = Math.ceil(data.length / threshold);
    const downsampled = [];

    for (let i = 0; i < data.length; i += bucketSize) {
        const bucketEnd = Math.min(i + bucketSize, data.length);
        if (bucketEnd <= i) continue;

        let minPoint = data[i];
        let maxPoint = data[i];

        for (let j = i + 1; j < bucketEnd; j++) {
            const point = data[j];
            if (point.v < minPoint.v) {
                minPoint = point;
            }
            if (point.v > maxPoint.v) {
                maxPoint = point;
            }
        }
        
        // Add points in chronological order
        if (minPoint.t < maxPoint.t) {
            downsampled.push(minPoint);
            downsampled.push(maxPoint);
        } else if (maxPoint.t < minPoint.t) {
            downsampled.push(maxPoint);
            downsampled.push(minPoint);
        } else {
            // If they have the same timestamp, just add one
            downsampled.push(minPoint);
        }
    }

    return downsampled;
}
