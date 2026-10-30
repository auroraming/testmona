import test from 'node:test';
import assert from 'node:assert/strict';
import { publishDeviceInventory, sanitizeDeviceInventory } from '../src/inventory.js';

test('sanitizes device inventory and refuses credential-shaped capabilities', () => {
  assert.deepEqual(sanitizeDeviceInventory([{
    external_id: 'emulator-5554', platform: 'Android', name: 'Pixel', capabilities: { sdk: 34 },
  }]), [{
    external_id: 'emulator-5554', platform: 'android', name: 'Pixel', capabilities: { sdk: 34 },
  }]);
  assert.throws(() => sanitizeDeviceInventory([{ external_id: 'x', platform: 'ios', capabilities: { token: 'abc' } }]), /credential/);
});

test('publishes inventory through the runner protocol', async () => {
  const calls = [];
  const result = await publishDeviceInventory({
    request: async (path, options) => {
      calls.push({ path, options });
      return [{ external_id: 'emulator-5554' }];
    },
  }, [{ external_id: 'emulator-5554', platform: 'android', name: 'Pixel' }]);
  assert.equal(calls[0].path, '/internal/ai-automation/devices/heartbeat');
  assert.equal(result[0].external_id, 'emulator-5554');
  assert.deepEqual(await publishDeviceInventory({ request: async () => { throw new Error('no'); } }, []), []);
});
