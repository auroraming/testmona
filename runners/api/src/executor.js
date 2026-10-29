const ACTIONS = new Set(['request', 'assert_status', 'assert_json_path', 'assert_header']);

function jsonPath(data, path) {
  const parts = String(path || '').replace(/^\$\.?/, '').split('.').filter(Boolean);
  return parts.reduce((value, part) => value == null ? undefined : value[part], data);
}

export function validateApiScript(script) {
  if (!Array.isArray(script) || script.length === 0) throw new Error('config.script must contain API steps');
  return script.map((step, index) => {
    if (!step || !ACTIONS.has(step.action)) throw new Error(`Unsupported API action at step ${index + 1}`);
    return step;
  });
}

export async function executeApiScript({ baseUrl, script, emitEvidence, fetchImpl = fetch, shouldCancel = () => false }) {
  const steps = validateApiScript(script);
  const origin = new URL(baseUrl).origin;
  let response = null;
  let responseBody = null;
  const assertions = [];
  for (let index = 0; index < steps.length; index += 1) {
    if (shouldCancel()) return { passed: false, cancelled: true, assertions, error: 'Task cancelled' };
    const step = steps[index];
    const sequence = index + 1;
    const startedAt = Date.now();
    let payload = { action: step.action };
    try {
      if (step.action === 'request') {
        const target = new URL(step.path || '/', baseUrl);
        if (target.origin !== origin) throw new Error('API request must stay within the configured base URL origin');
        response = await fetchImpl(target, {
          method: String(step.method || 'GET').toUpperCase(),
          headers: { 'content-type': 'application/json', ...(step.headers || {}) },
          body: step.body == null ? undefined : JSON.stringify(step.body),
          signal: AbortSignal.timeout(Number(step.timeout_ms || 30000)),
        });
        const text = await response.text();
        try { responseBody = text ? JSON.parse(text) : null; } catch { responseBody = text; }
        payload = { ...payload, method: step.method || 'GET', path: target.pathname, status_code: response.status };
      } else {
        if (!response) throw new Error('Assertion requires a preceding request step');
        let expected; let actual;
        if (step.action === 'assert_status') { expected = Number(step.expected); actual = response.status; }
        if (step.action === 'assert_json_path') { expected = step.expected; actual = jsonPath(responseBody, step.path); }
        if (step.action === 'assert_header') { expected = String(step.expected); actual = response.headers.get(step.name); }
        const passed = JSON.stringify(actual) === JSON.stringify(expected);
        const assertion = { passed, expected, actual, path: step.path, name: step.name };
        assertions.push(assertion);
        payload = { ...payload, assertion };
        if (!passed) throw new Error(`${step.action} failed`);
      }
      payload.duration_ms = Date.now() - startedAt;
      await emitEvidence({ sequence, evidence_type: step.action.startsWith('assert_') ? 'assertion' : 'network', title: step.action, status: step.action.startsWith('assert_') ? 'passed' : 'completed', payload });
    } catch (error) {
      payload.duration_ms = Date.now() - startedAt;
      payload.error = error instanceof Error ? error.message : 'API step failed';
      await emitEvidence({ sequence, evidence_type: step.action.startsWith('assert_') ? 'assertion' : 'network', title: step.action, status: 'failed', payload });
      return { passed: false, assertions, error: payload.error, completed_steps: sequence };
    }
  }
  return { passed: assertions.length > 0 && assertions.every((item) => item.passed), assertions, error: assertions.length ? null : 'An API script must contain an explicit assertion', completed_steps: steps.length };
}
