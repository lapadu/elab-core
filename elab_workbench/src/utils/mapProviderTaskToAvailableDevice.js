import { COLOR_PALETTE } from './Shared.jsx';

export function mapProviderTaskToAvailableDevice(provider, task) {
  const deviceId = task.id;
  const colorIndex = [...deviceId].reduce((acc, char) => acc + char.charCodeAt(0), 0) % COLOR_PALETTE.length;

  return {
    id: deviceId,
    originalId: task.originalId || deviceId,
    name: task.name || provider.name,
    type: task.type || 'SENSOR',
    groupId: task.groupId || 'generic',
    providerId: provider.id,
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