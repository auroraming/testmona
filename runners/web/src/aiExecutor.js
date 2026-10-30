import { PlaywrightAssertionProxy, normalizeHttpOrigin } from './assertionProxy.js';
import { DEFAULT_PLAYWRIGHT_MCP_PACKAGE, startPlaywrightMcpWorker } from './mcpWorker.js';

const PINNED_PACKAGE = /^@playwright\/mcp@\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$/u;

export function resolveAllowedOrigin(context) {
  const config = context?.environment?.config;
  if (!config || typeof config !== 'object') throw new Error('Web AI tasks require an environment app_url or base_url');
  for (const key of ['app_url', 'base_url']) {
    if (typeof config[key] === 'string' && config[key].trim()) return normalizeHttpOrigin(config[key]);
  }
  throw new Error('Web AI tasks require an environment app_url or base_url');
}

export function resolvePackage(task, override) {
  const configured = typeof task?.config?.playwright_mcp_package === 'string' ? task.config.playwright_mcp_package.trim() : '';
  const packageRef = override || configured || process.env.TESTMONA_PLAYWRIGHT_MCP_PACKAGE || DEFAULT_PLAYWRIGHT_MCP_PACKAGE;
  if (!PINNED_PACKAGE.test(packageRef)) throw new Error('playwright_mcp_package must pin an exact @playwright/mcp semantic version');
  return packageRef;
}

function buildGoal(lease) {
  const parts = [String(lease.context?.goal || lease.task.goal || '').trim()];
  if (lease.context?.test_case) {
    parts.push(`Test case: ${JSON.stringify(lease.context.test_case).slice(0, 6000)}`);
  }
  parts.push('Use browser_assert_text, browser_assert_visible, browser_assert_url, or browser_assert_network for explicit assertions. Navigation and clicks do not pass the test.');
  return parts.filter(Boolean).join('\n');
}

function renderPrompt(lease, tools, steps) {
  return [
    'You are TestMona\'s constrained test automation agent. Choose exactly one next action. ',
    'Return JSON only: either {"type":"tool","tool":"name","arguments":{...}} or {"type":"finish","summary":"..."}. ',
    'Never claim success merely because a tool ran; assertions must be explicit tool results.',
    `Goal: ${buildGoal(lease)}`,
    `Allowed tools: ${JSON.stringify(tools)}`,
    `Completed steps: ${JSON.stringify(steps)}`,
  ].join('\n');
}

function buildPrompt(lease, tools, steps) {
  let history = steps;
  let prompt = renderPrompt(lease, tools, history);
  while (prompt.length > 11000 && history.length) {
    history = history.slice(1);
    prompt = renderPrompt(lease, tools, history);
  }
  return prompt.slice(0, 11000);
}

export function parseDecision(content) {
  const start = String(content || '').indexOf('{');
  const end = String(content || '').lastIndexOf('}');
  if (start < 0 || end <= start) throw new Error('invalid');
  const data = JSON.parse(content.slice(start, end + 1));
  const type = String(data.type || '').trim().toLowerCase();
  if (!['tool', 'finish'].includes(type)) throw new Error('invalid');
  if (type === 'tool' && !data.tool) throw new Error('invalid');
  return { type, tool: data.tool, arguments: data.arguments || {}, summary: data.summary || null };
}

function hasPassingAssertion(steps) {
  return steps.some((step) => step.tool.toLowerCase().includes('assert') && step.output?.structured_content?.passed === true);
}

function evidenceFor(step) {
  const name = step.tool.toLowerCase();
  const evidenceType = name.includes('assert') ? 'assertion' : name.includes('network') ? 'network' : name.includes('screenshot') ? 'screenshot' : 'step';
  const passed = step.output?.structured_content?.passed;
  return {
    sequence: step.sequence,
    evidence_type: evidenceType,
    title: step.tool,
    status: step.error || passed === false ? 'failed' : 'completed',
    payload: {
      arguments: step.arguments,
      output: {
        structured_content: step.output?.structured_content || null,
        text: (step.output?.content || []).filter((item) => item?.type === 'text').map((item) => item.text).join('\n').slice(0, 4000),
      },
      error: step.error,
    },
  };
}

function failed(code, message, retryable, inputTokens, outputTokens, steps) {
  return {
    status: 'failed',
    body: { summary: null, step_count: steps.length, error: { code, message, retryable } },
    errorMessage: message,
    inputTokens,
    outputTokens,
  };
}

export async function runWebAiLoop({ lease, protocol, proxy, now = Date.now }) {
  const maxSteps = lease.task.max_steps || 50;
  const timeoutMs = (lease.task.timeout_seconds || 900) * 1000;
  const tokenBudget = lease.task.token_budget ?? null;
  const started = now();
  const steps = [];
  let inputTokens = 0;
  let outputTokens = 0;
  const tools = await proxy.discoverTools();
  if (!tools.length) return failed('no_tools', 'No authorized MCP tools are available', false, inputTokens, outputTokens, steps);
  for (let index = 0; index < maxSteps; index += 1) {
    const heartbeat = await protocol.heartbeat(lease);
    if (heartbeat.cancel_requested) {
      return { status: 'cancelled', body: { summary: null, step_count: steps.length }, errorMessage: null, inputTokens, outputTokens };
    }
    if (now() - started >= timeoutMs) return failed('timeout', 'Agent Runtime exceeded its task timeout', true, inputTokens, outputTokens, steps);
    if (tokenBudget != null && inputTokens + outputTokens >= tokenBudget) {
      return failed('token_budget_exceeded', 'Agent Runtime exhausted its token budget', false, inputTokens, outputTokens, steps);
    }
    const maxTokens = tokenBudget == null ? 800 : Math.max(1, Math.min(800, tokenBudget - inputTokens - outputTokens));
    let completion;
    try {
      completion = await protocol.complete(lease, buildPrompt(lease, tools, steps), maxTokens);
    } catch (error) {
      return failed('ai_unavailable', error instanceof Error ? error.message : 'AI completion failed', true, inputTokens, outputTokens, steps);
    }
    inputTokens += completion.prompt_tokens || 0;
    outputTokens += completion.completion_tokens || 0;
    if (tokenBudget != null && inputTokens + outputTokens > tokenBudget) {
      return failed('token_budget_exceeded', 'AI response exceeded the task token budget', false, inputTokens, outputTokens, steps);
    }
    let decision;
    try { decision = parseDecision(completion.content); }
    catch { return failed('invalid_model_output', 'AI returned an invalid agent decision', false, inputTokens, outputTokens, steps); }
    if (decision.type === 'finish') {
      if (!hasPassingAssertion(steps)) {
        return failed('missing_assertion', 'AI cannot finish successfully without a passing assertion tool result', false, inputTokens, outputTokens, steps);
      }
      return { status: 'passed', body: { summary: decision.summary, step_count: steps.length, error: null }, errorMessage: null, inputTokens, outputTokens };
    }
    const step = { sequence: steps.length + 1, tool: decision.tool, arguments: decision.arguments, output: null, error: null };
    try {
      step.output = await proxy.callTool(step.tool, step.arguments);
    } catch (error) {
      step.error = { code: 'tool_error', message: error instanceof Error ? error.message : 'Tool failed', retryable: false };
      steps.push(step);
      await protocol.appendEvidence(lease, [evidenceFor(step)]);
      return failed(step.error.code, step.error.message, false, inputTokens, outputTokens, steps);
    }
    steps.push(step);
    await protocol.appendEvidence(lease, [evidenceFor(step)]);
  }
  return failed('max_steps_exceeded', 'Agent Runtime reached the maximum number of steps', false, inputTokens, outputTokens, steps);
}

export async function executeWebAi(lease, dependencies) {
  const protocol = dependencies.protocol;
  const sessionFactory = dependencies.sessionFactory || startPlaywrightMcpWorker;
  let session = null;
  let started = false;
  let result;
  try {
    const origin = resolveAllowedOrigin(lease.context);
    const packageRef = resolvePackage(lease.task, dependencies.packageRef);
    session = await sessionFactory({
      packageRef,
      allowedOrigin: origin,
      workspace: dependencies.workspace || process.env.TESTMONA_PLAYWRIGHT_WORKSPACE || '/runner/artifacts',
    });
    started = true;
    const proxy = new PlaywrightAssertionProxy(session.client, origin);
    result = await runWebAiLoop({ lease, protocol, proxy, now: dependencies.now });
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Playwright MCP worker failed';
    result = {
      status: started ? 'failed' : 'blocked',
      body: { error: { code: started ? 'worker_error' : 'blocked', message } },
      errorMessage: message,
      inputTokens: 0,
      outputTokens: 0,
    };
  } finally {
    await session?.stop();
  }
  await protocol.report(lease, result.status, result.body, result.errorMessage, result.inputTokens, result.outputTokens);
  return result;
}
