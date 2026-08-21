// Replay stream namespacing.
//
// The server-side replayer publishes recorded samples under a "rec_"-prefixed
// sourceId so a recording behaves like an independent source. Live and
// replayed samples must never share a stream buffer.

export const REPLAY_ID_PREFIX = 'rec_';

/** Prefix an id into the replay namespace (idempotent). */
export const toReplayId = (id) =>
  typeof id === 'string' && !id.startsWith(REPLAY_ID_PREFIX) ? `${REPLAY_ID_PREFIX}${id}` : id;

/** True when the id belongs to the replay namespace. */
export const isReplayId = (id) => typeof id === 'string' && id.startsWith(REPLAY_ID_PREFIX);

/**
 * Read-only view on the shared stream-buffer Map for a recorded task.
 *
 * Only the widget's OWN live id is shadowed by its recording: templates and
 * channels look data up by `originalId`, which would otherwise hit the still
 * streaming sensor the recording was made from. Every other id passes through
 * unchanged, so a recording can deliberately be charted together with live
 * sources (e.g. a generator) in one widget.
 *
 * Implemented as a Proxy rather than a copied Map because buffers are created
 * lazily on the first sample; the traps therefore always see current state.
 *
 * @param {Map<string, any>} streamBuffers
 * @param {string} liveId id of the live source this recording was made from
 * @returns {Map<string, any>} proxied map
 */
export const createRecordedBufferView = (streamBuffers, liveId) => {
  // Nothing to shadow when the id is already unambiguous.
  if (!streamBuffers || !liveId || isReplayId(liveId)) return streamBuffers;

  const recId = toReplayId(liveId);
  const resolve = (key) => (key === liveId ? recId : key);

  // The live buffer of the recorded source is hidden; the recording takes its
  // place under both id styles.
  const visibleEntries = (target) => {
    const out = [];
    target.forEach((buffer, id) => {
      if (id === liveId) return;
      out.push([id, buffer]);
      if (id === recId) out.push([liveId, buffer]);
    });
    return out;
  };

  return new Proxy(streamBuffers, {
    get(target, prop, receiver) {
      if (prop === 'get') return (key) => target.get(resolve(key));
      if (prop === 'has') return (key) => target.has(resolve(key));
      if (prop === 'size') return visibleEntries(target).length;
      if (prop === 'entries' || prop === Symbol.iterator) {
        return () => visibleEntries(target)[Symbol.iterator]();
      }
      if (prop === 'keys') {
        return () => visibleEntries(target).map(([k]) => k)[Symbol.iterator]();
      }
      if (prop === 'values') {
        return () => visibleEntries(target).map(([, v]) => v)[Symbol.iterator]();
      }
      if (prop === 'forEach') {
        return (cb, thisArg) =>
          visibleEntries(target).forEach(([k, v]) => cb.call(thisArg, v, k, receiver));
      }
      const val = Reflect.get(target, prop, receiver);
      return typeof val === 'function' ? val.bind(target) : val;
    },
  });
};
