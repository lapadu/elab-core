import { describe, it, expect } from 'vitest';
import {
  REPLAY_ID_PREFIX,
  toReplayId,
  isReplayId,
  createRecordedBufferView,
} from './replayStreams';

const makeBuffers = () =>
  new Map([
    ['sensor_1', 'LIVE_BUFFER'],
    ['rec_sensor_1', 'REC_BUFFER'],
    ['sensor_2', 'LIVE_ONLY'],
  ]);

describe('replay id helpers', () => {
  it('prefixes live ids and stays idempotent', () => {
    expect(toReplayId('sensor_1')).toBe(`${REPLAY_ID_PREFIX}sensor_1`);
    expect(toReplayId('rec_sensor_1')).toBe('rec_sensor_1');
  });

  it('detects the replay namespace', () => {
    expect(isReplayId('rec_x')).toBe(true);
    expect(isReplayId('x')).toBe(false);
  });
});

describe('createRecordedBufferView', () => {
  it('redirects the recorded source id to its replay buffer', () => {
    const view = createRecordedBufferView(makeBuffers(), 'sensor_1');
    expect(view.get('sensor_1')).toBe('REC_BUFFER');
    expect(view.get('rec_sensor_1')).toBe('REC_BUFFER');
    expect(view.has('sensor_1')).toBe(true);
  });

  it('never falls back to the live buffer of the recorded source', () => {
    const buffers = new Map([['sensor_1', 'LIVE_BUFFER']]);
    const view = createRecordedBufferView(buffers, 'sensor_1');
    expect(view.get('sensor_1')).toBeUndefined();
    expect(view.has('sensor_1')).toBe(false);
    expect(Array.from(view.keys())).toEqual([]);
  });

  it('passes other live sources through so they can be mixed in', () => {
    const view = createRecordedBufferView(makeBuffers(), 'sensor_1');
    expect(view.get('sensor_2')).toBe('LIVE_ONLY');
    expect(view.has('sensor_2')).toBe(true);
  });

  it('exposes the recording under both id styles and hides the shadowed live buffer', () => {
    const view = createRecordedBufferView(makeBuffers(), 'sensor_1');
    const entries = Object.fromEntries(Array.from(view.entries()));
    expect(entries).toEqual({
      rec_sensor_1: 'REC_BUFFER',
      sensor_1: 'REC_BUFFER',
      sensor_2: 'LIVE_ONLY',
    });
    expect(view.size).toBe(3);
  });

  it('sees buffers created after the view was built', () => {
    const buffers = new Map();
    const view = createRecordedBufferView(buffers, 'late');
    expect(view.get('late')).toBeUndefined();
    buffers.set('rec_late', 'REC_LATE');
    expect(view.get('late')).toBe('REC_LATE');
  });

  it('is a pass-through when the id is already a replay id', () => {
    const buffers = makeBuffers();
    expect(createRecordedBufferView(buffers, 'rec_sensor_1')).toBe(buffers);
  });

  it('forEach reports the visible buffers with their keys', () => {
    const view = createRecordedBufferView(makeBuffers(), 'sensor_1');
    const seen = new Map();
    view.forEach((buffer, id) => seen.set(id, buffer));
    expect(seen.get('sensor_1')).toBe('REC_BUFFER');
    expect(seen.get('rec_sensor_1')).toBe('REC_BUFFER');
    expect(seen.get('sensor_2')).toBe('LIVE_ONLY');
  });
});
