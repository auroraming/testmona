import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdir, mkdtemp, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { buildPrompt, executeWebAi, runWebAiLoop } from '../src/aiExecutor.js';

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

test('uploads screenshot, trace, and console log before the worker stops', async () => {
  const dir = await mkdtemp(path.join(tmpdir(), 'ai-evidence-'));
  await writeFile(path.join(dir, 'page.png'), Buffer.from('png'));
  const runner = protocol([
    '{"type":"tool","tool":"browser_take_screenshot","arguments":{}}',
    '{"type":"tool","tool":"browser_assert_text","arguments":{"expected":"Welcome"}}',
    '{"type":"finish","summary":"Title is visible"}',
  ]);
  runner.uploadArtifact = async (_lease, _bytes, filename) => ({ artifact_ref: `ai-automation/7/${filename}` });
  let stopped = 0;
  const result = await executeWebAi(lease(), {
    protocol: runner,
    sessionFactory: async () => ({
      outputDir: dir,
      client: {
        async listTools() {
          return [{ name: 'browser_snapshot', description: 'snapshot' }, { name: 'browser_take_screenshot', description: 'shot' }];
        },
        async callTool(name) {
          if (name === 'browser_console_messages') return { content: [{ type: 'text', text: 'console ready' }] };
          if (name === 'browser_stop_tracing') {
            await mkdir(path.join(dir, 'traces'), { recursive: true });
            await writeFile(path.join(dir, 'traces', 'trace-99.trace'), Buffer.from('PK'));
            await writeFile(path.join(dir, 'traces', 'trace-99.network'), Buffer.from('net'));
            return { content: [] };
          }
          if (name === 'browser_snapshot') return { content: [{ type: 'text', text: 'heading "Welcome"' }] };
          return { content: [{ type: 'text', text: 'saved ./page.png' }] };
        },
      },
      async stop() {
        stopped += 1;
        await rm(dir, { recursive: true, force: true });
      },
    }),
  });
  assert.equal(result.status, 'passed');
  const screenshot = runner.events.evidence.find((item) => item.evidence_type === 'screenshot');
  const trace = runner.events.evidence.find((item) => item.evidence_type === 'trace');
  const log = runner.events.evidence.find((item) => item.evidence_type === 'log');
  assert.equal(screenshot.artifact_ref, 'ai-automation/7/page.png');
  assert.match(trace.artifact_ref, /trace-99\.trace/);
  assert.match(log.artifact_ref, /console\.txt/);
  assert.equal(stopped, 1);
});

test('keeps completed steps when tool schemas exceed the prompt budget', () => {
  const tools = Array.from({ length: 30 }, (_, index) => ({
    name: `browser_tool_${index}`,
    description: 'd'.repeat(400),
    input_schema: { type: 'object', properties: { blob: { type: 'string', description: 's'.repeat(4000) } } },
  }));
  const steps = [{
    sequence: 1,
    tool: 'browser_snapshot',
    arguments: { target: 'e1' },
    output: { structured_content: { passed: false }, content: [{ type: 'text', text: 'heading Welcome' }] },
    error: null,
  }];
  const prompt = buildPrompt(lease(), tools, steps);
  assert.ok(prompt.includes('Completed steps:'));
  assert.ok(prompt.includes('browser_snapshot'));
  assert.equal(prompt.includes('s'.repeat(200)), false);
  assert.ok(prompt.length <= 12000);
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
