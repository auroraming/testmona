import test from 'node:test';
import assert from 'node:assert/strict';
import { PlaywrightAssertionProxy } from '../src/assertionProxy.js';

function browser(pages) {
  const calls = [];
  return {
    calls,
    async listTools() {
      return [
        { name: 'browser_snapshot', description: 'snapshot' },
        { name: 'browser_navigate', description: 'navigate' },
        { name: 'browser_network_requests', description: 'network' },
        { name: 'browser_network_request', description: 'detail' },
        { name: 'browser_run_code_unsafe', description: 'unsafe' },
        { name: 'browser_tabs', description: 'tabs' },
      ];
    },
    async callTool(name, args) {
      calls.push([name, args]);
      return pages[name] || { content: [{ type: 'text', text: '' }] };
    },
  };
}

test('discovery adds assertions and hides unsafe tools', async () => {
  const proxy = new PlaywrightAssertionProxy(browser({}), 'https://example.test');
  const names = (await proxy.discoverTools()).map((tool) => tool.name);
  assert.ok(names.includes('browser_assert_text'));
  assert.equal(names.includes('browser_run_code_unsafe'), false);
  assert.equal(names.includes('browser_network_request'), false);
});

test('text, visibility, url, and network assertions are explicit', async () => {
  const client = browser({
    browser_snapshot: { content: [{ type: 'text', text: '- heading "Welcome"\n- button "Sign in"' }] },
    browser_tabs: { content: [{ type: 'text', text: '- 0: (current) [Home](https://example.test/login)' }] },
    browser_network_requests: { content: [{ type: 'text', text: '[GET] https://example.test/api/orders => [201] Created\n[GET] https://evil.test/api/orders => [201] Created' }] },
  });
  const proxy = new PlaywrightAssertionProxy(client, 'https://example.test');
  assert.equal((await proxy.callTool('browser_assert_text', { expected: 'Welcome' })).structured_content.passed, true);
  assert.equal((await proxy.callTool('browser_assert_visible', { name: 'Sign in' })).structured_content.passed, true);
  assert.equal((await proxy.callTool('browser_assert_text', { expected: 'Goodbye' })).structured_content.passed, false);
  assert.equal((await proxy.callTool('browser_assert_url', { expected: '/login' })).structured_content.passed, true);
  assert.equal((await proxy.callTool('browser_assert_url', { expected: 'https://evil.test/login' })).structured_content.passed, false);
  assert.equal((await proxy.callTool('browser_assert_network', { url_contains: '/api/orders', method: 'get', status: 201 })).structured_content.passed, true);
  assert.equal((await proxy.callTool('browser_assert_network', { url_contains: 'https://evil.test' })).structured_content.passed, false);
});

test('navigation outside the origin is not sent to the browser', async () => {
  const client = browser({});
  const proxy = new PlaywrightAssertionProxy(client, 'https://example.test');
  await assert.rejects(() => proxy.callTool('browser_navigate', { url: 'https://evil.test', filename: 'x.txt', token: 'secret' }), /allowed origin/);
  assert.deepEqual(client.calls, []);
  await proxy.callTool('browser_navigate', { url: 'https://example.test/login', filename: 'x.txt' });
  assert.deepEqual(client.calls, [['browser_navigate', { url: 'https://example.test/login' }]]);
});
