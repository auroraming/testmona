import test from 'node:test';
import assert from 'node:assert/strict';
import { executeWebAi, runWebAiLoop } from '../src/aiExecutor.js';

function protocol(decisions) {
  const events = { evidence: [], reports: [], completions: 0 };
  return {
    events,
    async heartbeat() { return { cancel_requested: false }; },
    async complete() {
      events.completions += 1;
      const content = decisions.shift();
      return { content, prompt_tokens: 2, completion_tokens: 1 };
    },
    async appendEvidence(_lease, items) { events.evidence.push(...items); },
    async report(lease, status, body, errorMessage, inputTokens, outputTokens) {
      events.reports.push({ lease, status, body, errorMessage, inputTokens, outputTokens });
    },
  };
}

function lease(context = { environment: { config: { app_url: 'https://example.test' } } }) {
  return {
    task: { id: 1, execution_mode: 'ai', max_steps: 3, timeout_seconds: 30, token_budget: 100, goal: 'Check title', config: {} },
    lease_token: 'lease',
    context,
  };
}

function sessionFactory(pages) {
  const calls = [];
  let stopped = 0;
  return {
    calls,
    stopped: () => stopped,
    async factory() {
      return {
        client: {
          async listTools() {
            return [{ name: 'browser_snapshot', description: 'snapshot' }, { name: 'browser_click', description: 'click' }];
          },
          async callTool(name, args) {
            calls.push([name, args]);
            return pages[name] || { content: [{ type: 'text', text: '' }] };
          },
        },
        async stop() { stopped += 1; },
      };
    },
  };
}

test('missing origin blocks the task without starting a browser', async () => {
  const runner = protocol([]);
  let started = false;
  const result = await executeWebAi(lease({}), {
    protocol: runner,
    sessionFactory: async () => { started = true; return { client: {}, async stop() {} }; },
  });
  assert.equal(started, false);
  assert.equal(result.status, 'blocked');
  assert.equal(runner.events.reports[0].status, 'blocked');
});

test('a click cannot pass and the worker stops afterwards', async () => {
  const runner = protocol([
    '{"type":"tool","tool":"browser_click","arguments":{"target":"e1"}}',
    '{"type":"finish","summary":"looks fine"}',
  ]);
  const session = sessionFactory({ browser_click: { structured_content: { clicked: true }, content: [] } });
  const result = await executeWebAi(lease(), { protocol: runner, sessionFactory: session.factory });
  assert.equal(result.status, 'failed');
  assert.equal(result.body.error.code, 'missing_assertion');
  assert.equal(session.stopped(), 1);
  assert.equal(runner.events.reports[0].status, 'failed');
});

test('an explicit passing assertion can finish the task', async () => {
  const runner = protocol([
    '{"type":"tool","tool":"browser_assert_text","arguments":{"expected":"Welcome"}}',
    '{"type":"finish","summary":"Title is visible"}',
  ]);
  const session = sessionFactory({
    browser_snapshot: { content: [{ type: 'text', text: 'heading "Welcome"' }] },
  });
  const result = await executeWebAi(lease(), { protocol: runner, sessionFactory: session.factory });
  assert.equal(result.status, 'passed');
  assert.equal(result.body.summary, 'Title is visible');
  assert.equal(runner.events.evidence[0].evidence_type, 'assertion');
  assert.equal(runner.events.reports[0].inputTokens, 4);
  assert.equal(session.stopped(), 1);
});

test('cancellation and startup failure stop cleanly', async () => {
  const runner = protocol([]);
  runner.heartbeat = async () => ({ cancel_requested: true });
  const cancelled = await runWebAiLoop({
    lease: lease(),
    protocol: runner,
    proxy: { async discoverTools() { return [{ name: 'browser_snapshot' }]; } },
  });
  assert.equal(cancelled.status, 'cancelled');
  assert.equal(runner.events.completions, 0);

  const blockedRunner = protocol([]);
  const failed = await executeWebAi(lease(), {
    protocol: blockedRunner,
    sessionFactory: async () => { throw new Error('browser down'); },
  });
  assert.equal(failed.status, 'blocked');
  assert.equal(blockedRunner.events.reports[0].status, 'blocked');
  let stopped = 0;
  const failedRunner = protocol([]);
  const started = await executeWebAi(lease(), {
    protocol: failedRunner,
    sessionFactory: async () => ({
      client: { async listTools() { throw new Error('tools failed'); } },
      async stop() { stopped += 1; },
    }),
  });
  assert.equal(started.status, 'failed');
  assert.equal(stopped, 1);
});
