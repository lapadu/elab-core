import { COLOR_PALETTE } from './Shared.jsx';

export function mapProviderTaskToAvailableDevice(provider, task) {
  const taskId = task.id;
  const colorIndex = [...taskId].reduce((acc, char) => acc + char.charCodeAt(0), 0) % COLOR_PALETTE.length;
  const device = provider.device || {};

  return {
    id: taskId,
    originalId: task.originalId || taskId,
    name: task.name || provider.name,
    alias: task.alias,
    type: task.type || 'SENSOR',
    groupId: task.groupId || 'generic',
    providerId: provider.id,
    // Instance identity of the physical unit. Legacy manifests without a
    // device block are single-provider devices.
    deviceId: device.id || provider.id,
    deviceName: device.name || provider.name,
    devicePersistCapable: device.persistCapable ?? false,
    // Type identity shared by every unit running the same firmware.
    model: device.model || null,
    deviceAnchor: device.anchor || 'ephemeral',
    color: task.color || COLOR_PALETTE[colorIndex],
    config: task.config || {},
    decimals: task.decimals,
    virtual: task.virtual ?? (provider.category === 'VIRTUAL_INTERNAL' || provider.category === 'VIRTUAL_SCRIPT'),
    category: provider.category || 'HARDWARE',
    tags: task.tags || [],
    actions: task.actions || [],
    ui: task.ui || { mode: 'generic', template: 'tpl_default' },
    clientIp: provider.client_ip,
  };
}