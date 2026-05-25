import { describe, expect, it } from 'vitest';

import { mapProviderTaskToAvailableDevice } from './App.jsx';

describe('mapProviderTaskToAvailableDevice', () => {
  it('preserves manifest actions for device tree payloads', () => {
    const provider = {
      id: 'prov-voltmeter',
      name: 'Voltmeter',
      category: 'HARDWARE',
      client_ip: '192.168.0.10',
    };
    const task = {
      id: 'esp32_voltmeter_01_ch1',
      name: 'CH1',
      type: 'SENSOR',
      actions: [{ id: 'START_RAW', label: 'RAW Capture', icon: 'Camera' }],
    };

    const device = mapProviderTaskToAvailableDevice(provider, task);

    expect(device.actions).toEqual(task.actions);
    expect(device.providerId).toBe(provider.id);
    expect(device.originalId).toBe(task.id);
  });
});