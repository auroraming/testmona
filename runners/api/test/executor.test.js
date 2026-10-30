import test from 'node:test';
import assert from 'node:assert/strict';
import { executeApiScript, validateApiScript } from '../src/executor.js';

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

test('injects a bearer credential without writing it to evidence and does not retry 401', async () => {
  const evidence = [];
  let calls = 0;
  let seenAuth = null;
  const secret = 'runner-only-secret-value';
  const result = await executeApiScript({
    baseUrl: 'https://api.example.test/',
    credentials: { 'api-token': secret },
    auth: { type: 'bearer', credential_ref: 'api-token' },
    script: [
      { action: 'request', path: '/private', retries: 2 },
      { action: 'assert_status', expected: 200 },
    ],
    fetchImpl: async (_url, options) => {
      calls += 1;
      seenAuth = options.headers.authorization;
      return new Response(JSON.stringify({ token: secret }), { status: 401 });
    },
    emitEvidence: async (item) => evidence.push(item),
  });
  assert.equal(seenAuth, `Bearer ${secret}`);
  assert.equal(calls, 1);
  assert.equal(result.passed, false);
  assert.equal(result.schema, 'testmona.api_result.v1');
  assert.equal(result.source, 'native_http');
  assert.doesNotMatch(JSON.stringify(evidence), new RegExp(secret));
});

test('substitutes variables and retries selected transient statuses', async () => {
  let calls = 0;
  const result = await executeApiScript({
    baseUrl: 'https://api.example.test/', variables: { tenant: 'acme' }, sleep: async () => {},
    script: [
      { action: 'request', path: 'tenant/${tenant}', retries: 1 },
      { action: 'assert_status', expected: 200 },
    ],
    fetchImpl: async (url) => {
      calls += 1;
      assert.equal(url.pathname, '/tenant/acme');
      return new Response('{}', { status: calls === 1 ? 503 : 200 });
    },
    emitEvidence: async () => {},
  });
  assert.equal(result.passed, true);
  assert.equal(calls, 2);
});

test('validates an OpenAPI-derived JSON response schema without storing the response body', async () => {
  const evidence = [];
  const schema = {
    type: 'object',
    required: ['id', 'items'],
    properties: {
      id: { type: 'integer' },
      items: { type: 'array', items: { type: 'object', required: ['name'], properties: { name: { type: 'string' } } } },
    },
  };
  const passed = await executeApiScript({
    baseUrl: 'https://api.example.test/',
    script: [{ action: 'request', path: '/catalog' }, { action: 'assert_json_schema', schema }],
    fetchImpl: async () => new Response(JSON.stringify({ id: 7, items: [{ name: 'book' }] })),
    emitEvidence: async (item) => evidence.push(item),
  });
  assert.equal(passed.passed, true);
  assert.equal(evidence[1].payload.assertion.actual, 'matched');
  assert.doesNotMatch(JSON.stringify(evidence), /book/);

  const failed = await executeApiScript({
    baseUrl: 'https://api.example.test/',
    script: [{ action: 'request', path: '/catalog' }, { action: 'assert_json_schema', schema }],
    fetchImpl: async () => new Response(JSON.stringify({ id: 'wrong', items: [{}] })),
    emitEvidence: async () => {},
  });
  assert.equal(failed.passed, false);
  assert.match(JSON.stringify(failed.assertions), /expected integer/);
  assert.match(JSON.stringify(failed.assertions), /required property is missing/);
});

test('rejects oversized response schemas before making a request', () => {
  const properties = Object.fromEntries(Array.from({ length: 501 }, (_, index) => [`field_${index}`, { type: 'string' }]));
  assert.throws(
    () => validateApiScript([{ action: 'assert_json_schema', schema: { type: 'object', properties } }]),
    /exceeds validation limits/,
  );
});
