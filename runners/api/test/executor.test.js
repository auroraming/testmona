import test from 'node:test';
import assert from 'node:assert/strict';
import { executeApiScript } from '../src/executor.js';

test('executes request and independent status/json assertions', async () => {
  const evidence = [];
  const fetchImpl = async () => new Response(JSON.stringify({ data: { healthy: true } }), { status: 200, headers: { 'x-build': '42' } });
  const result = await executeApiScript({
    baseUrl: 'https://api.example.test/v1/', fetchImpl,
    script: [
      { action: 'request', method: 'GET', path: 'health' },
      { action: 'assert_status', expected: 200 },
      { action: 'assert_json_path', path: '$.data.healthy', expected: true },
      { action: 'assert_header', name: 'x-build', expected: '42' },
    ],
    emitEvidence: async (item) => evidence.push(item),
  });
  assert.equal(result.passed, true);
  assert.equal(result.assertions.length, 3);
  assert.equal(evidence[0].evidence_type, 'network');
});

test('blocks requests that escape the configured origin', async () => {
  const result = await executeApiScript({
    baseUrl: 'https://api.example.test/',
    script: [{ action: 'request', path: 'https://evil.example/steal' }],
    fetchImpl: async () => { throw new Error('must not run'); },
    emitEvidence: async () => {},
  });
  assert.equal(result.passed, false);
  assert.match(result.error, /configured base URL origin/);
});
