import test from 'node:test';
import assert from 'node:assert/strict';
import { executeScript } from '../src/executor.js';

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

test('does not pass a script with no assertions', async () => {
  const result = await executeScript(fakePage(), [{ action: 'click', selector: '#save' }], async () => {});
  assert.equal(result.passed, false);
  assert.match(result.error, /explicit assertion/);
});
