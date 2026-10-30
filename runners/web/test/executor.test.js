import test from 'node:test';
import assert from 'node:assert/strict';
import { executeScript, redactUrl } from '../src/executor.js';

function fakePage(text = 'Welcome') {
  const locator = {
    click: async () => {}, fill: async () => {}, textContent: async () => text, isVisible: async () => true,
  };
  return {
    goto: async () => {}, url: () => 'https://example.test/', locator: () => locator, screenshot: async () => {},
  };
}

test('executes actions and requires an explicit passing assertion', async () => {
  const evidence = [];
  const result = await executeScript(fakePage(), [
    { action: 'navigate', url: 'https://example.test' },
    { action: 'click', selector: '#login' },
    { action: 'fill', selector: '#name', value: 'tester' },
    { action: 'assert_text', selector: 'h1', expected: 'Welcome' },
  ], async (item) => evidence.push(item));
  assert.equal(result.passed, true);
  assert.equal(evidence.length, 4);
  assert.equal(evidence.at(-1).evidence_type, 'assertion');
});

test('captures redacted network metadata without bodies or secrets', async () => {
  const evidence = [];
  const listeners = {};
  const request = {
    method: () => 'GET',
    url: () => 'https://user:secretpass@staging.example.test/orders?token=abc123&page=1#session',
    resourceType: () => 'fetch',
  };
  const page = {
    ...fakePage(),
    on: (event, handler) => { listeners[event] = handler; },
    goto: async () => {
      listeners.request(request);
      listeners.response({ status: () => 204, request: () => request });
    },
  };
  const result = await executeScript(page, [
    { action: 'navigate', url: 'https://staging.example.test/orders' },
    { action: 'assert_text', selector: 'h1', expected: 'Welcome' },
  ], async (item) => evidence.push(item));
  assert.equal(result.passed, true);
  const network = evidence.find((item) => item.evidence_type === 'network');
  assert.equal(network.sequence, 700001);
  assert.equal(network.payload.method, 'GET');
  assert.equal(network.payload.status, 204);
  assert.equal(network.payload.resource_type, 'fetch');
  assert.doesNotMatch(JSON.stringify(network), /secretpass|abc123|session/);
  assert.match(network.payload.url, /page=1/);
  assert.equal(redactUrl('not a url'), '[invalid-url]');
});

test('does not pass a script with no assertions', async () => {
  const result = await executeScript(fakePage(), [{ action: 'click', selector: '#save' }], async () => {});
  assert.equal(result.passed, false);
  assert.match(result.error, /explicit assertion/);
});
