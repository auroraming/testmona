import test from 'node:test';
import assert from 'node:assert/strict';
import { executeMobileScript, mobilePreflightBlock } from '../src/executor.js';

const driver = {
  find: async () => 'element-1', click: async () => {}, type: async () => {},
  text: async () => 'Signed in', swipe: async () => {}, screenshot: async () => 'cG5n',
};

test('executes touch actions and explicit text assertion', async () => {
  const evidence = [];
  const result = await executeMobileScript(driver, [
    { action: 'tap', selector: { strategy: 'accessibility_id', value: 'login' } },
    { action: 'type', selector: { strategy: 'id', value: 'username' }, value: 'tester' },
    { action: 'assert_text', selector: { strategy: 'xpath', value: '//title' }, expected: 'Signed' },
  ], async (item) => evidence.push(item));
  assert.equal(result.passed, true);
  assert.equal(evidence.at(-1).evidence_type, 'assertion');
});

test('never passes action-only mobile scripts', async () => {
  const result = await executeMobileScript(driver, [{ action: 'swipe', start_x: 1, start_y: 2, end_x: 3, end_y: 4 }], async () => {});
  assert.equal(result.passed, false);
  assert.match(result.error, /explicit assertion/);
});

test('explains missing Appium and unavailable mobile AI integration', () => {
  assert.equal(mobilePreflightBlock('', 'script'), 'No Appium endpoint is configured');
  assert.equal(mobilePreflightBlock('http://appium:4723', 'ai'), 'Mobile AI mode requires mobile-mcp integration');
  assert.equal(mobilePreflightBlock('http://appium:4723', 'script'), null);
});
