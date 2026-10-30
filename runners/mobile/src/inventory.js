const PLATFORMS = new Set(['android', 'ios']);

export function sanitizeDeviceInventory(devices) {
  if (!Array.isArray(devices)) return [];
  return devices.slice(0, 50).map((device) => {
    const platform = String(device?.platform || '').toLowerCase();
    const externalId = String(device?.external_id || '').trim();
    const name = String(device?.name || externalId).trim();
    if (!PLATFORMS.has(platform) || !externalId || externalId.length > 120) {
      throw new Error('Device inventory entries need an android or ios platform and an external id');
    }
    const capabilities = device.capabilities && typeof device.capabilities === 'object' ? device.capabilities : {};
    const serialized = JSON.stringify(capabilities).toLowerCase();
    if (/(password|secret|token|authorization)/.test(serialized)) {
      throw new Error('Device capabilities cannot contain credential fields');
    }
    return { external_id: externalId, platform, name: name.slice(0, 120), capabilities };
  });
}

export async function publishDeviceInventory(protocol, devices) {
  const sanitized = sanitizeDeviceInventory(devices);
  if (!sanitized.length) return [];
  return protocol.request('/internal/ai-automation/devices/heartbeat', {
    method: 'POST',
    body: JSON.stringify({ devices: sanitized }),
  });
}
