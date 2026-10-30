import { normalizeApiResult } from './result.js';

const ACTIONS = new Set(['request', 'assert_status', 'assert_json_path', 'assert_header']);
const NON_RETRYABLE_STATUSES = new Set([401, 403]);

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

function substitute(value, variables) {
  if (typeof value === 'string') return value.replace(/\$\{([A-Za-z_][A-Za-z0-9_]*)\}/g, (_match, name) => {
    if (!(name in variables)) throw new Error(`Missing API variable: ${name}`);
    return String(variables[name]);
  });
  if (Array.isArray(value)) return value.map((item) => substitute(item, variables));
  if (value && typeof value === 'object') return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, substitute(item, variables)]));
  return value;
}

function redactSecrets(value, credentials) {
  const secrets = Object.values(credentials).filter((item) => typeof item === 'string' && item.length >= 6);
  const walk = (item) => {
    if (typeof item === 'string') {
      return secrets.reduce((text, secret) => text.split(secret).join('[redacted]'), item);
    }
    if (Array.isArray(item)) return item.map(walk);
    if (item && typeof item === 'object') {
      return Object.fromEntries(Object.entries(item).map(([key, child]) => [key, walk(child)]));
    }
    return item;
  };
  return walk(value);
}

function applyAuth(headers, auth, credentials) {
  if (!auth) return headers;
  const secret = credentials[auth.credential_ref];
  if (!secret) throw new Error(`Missing credential reference: ${auth.credential_ref}`);
  if (auth.type === 'bearer') return { ...headers, authorization: `Bearer ${secret}` };
  if (auth.type === 'header') return { ...headers, [auth.header]: secret };
  throw new Error('Unsupported credential auth type');
}

export async function executeApiScript({ baseUrl, script, variables = {}, credentials = {}, auth = null, emitEvidence, fetchImpl = fetch, shouldCancel = () => false, sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms)) }) {
  const steps = validateApiScript(script);
  const origin = new URL(baseUrl).origin;
  let response = null;
  let responseBody = null;
  const assertions = [];
  for (let index = 0; index < steps.length; index += 1) {
    if (shouldCancel()) return normalizeApiResult('native_http', { passed: false, cancelled: true, assertions, error: 'Task cancelled', completed_steps: index });
    const step = steps[index];
    const sequence = index + 1;
    const startedAt = Date.now();
    let payload = { action: step.action };
    try {
      if (step.action === 'request') {
        const resolved = substitute(step, variables);
        const target = new URL(resolved.path || '/', baseUrl);
        if (target.origin !== origin) throw new Error('API request must stay within the configured base URL origin');
        if (target.username || target.password) throw new Error('API request URL cannot embed credentials');
        const retries = Math.max(0, Math.min(3, Number(resolved.retries || 0)));
        const retryStatuses = new Set(resolved.retry_on_status || [429, 502, 503, 504]);
        let attempt = 0;
        const headers = applyAuth({ 'content-type': 'application/json', ...(resolved.headers || {}) }, auth, credentials);
        while (true) {
          attempt += 1;
          try {
            response = await fetchImpl(target, {
              method: String(resolved.method || 'GET').toUpperCase(),
              headers,
              body: resolved.body == null ? undefined : JSON.stringify(resolved.body),
              signal: AbortSignal.timeout(Number(resolved.timeout_ms || 30000)),
            });
            if (attempt > retries || NON_RETRYABLE_STATUSES.has(response.status) || !retryStatuses.has(response.status)) break;
          } catch (error) {
            if (attempt > retries) throw error;
          }
          await sleep(Math.min(2000, Number(resolved.retry_backoff_ms || 250) * (2 ** (attempt - 1))));
        }
        const text = await response.text();
        try { responseBody = text ? JSON.parse(text) : null; } catch { responseBody = text; }
        payload = { ...payload, method: resolved.method || 'GET', path: target.pathname, status_code: response.status, attempts: attempt };
      } else {
        if (!response) throw new Error('Assertion requires a preceding request step');
        let expected; let actual;
        if (step.action === 'assert_status') { expected = Number(step.expected); actual = response.status; }
        if (step.action === 'assert_json_path') { expected = step.expected; actual = jsonPath(responseBody, step.path); }
        if (step.action === 'assert_header') { expected = String(step.expected); actual = response.headers.get(step.name); }
        const passed = JSON.stringify(actual) === JSON.stringify(expected);
        const assertion = { passed, expected, actual, path: step.path, name: step.name };
        assertions.push(assertion);
        payload = { ...payload, assertion: redactSecrets(assertion, credentials) };
        if (!passed) throw new Error(`${step.action} failed`);
      }
      payload = redactSecrets(payload, credentials);
      payload.duration_ms = Date.now() - startedAt;
      await emitEvidence({ sequence, evidence_type: step.action.startsWith('assert_') ? 'assertion' : 'network', title: step.action, status: step.action.startsWith('assert_') ? 'passed' : 'completed', payload });
    } catch (error) {
      payload = redactSecrets(payload, credentials);
      payload.duration_ms = Date.now() - startedAt;
      payload.error = redactSecrets(error instanceof Error ? error.message : 'API step failed', credentials);
      await emitEvidence({ sequence, evidence_type: step.action.startsWith('assert_') ? 'assertion' : 'network', title: step.action, status: 'failed', payload });
      return normalizeApiResult('native_http', { passed: false, assertions: redactSecrets(assertions, credentials), error: payload.error, completed_steps: sequence });
    }
  }
  const passed = assertions.length > 0 && assertions.every((item) => item.passed);
  return normalizeApiResult('native_http', {
    passed,
    assertions: redactSecrets(assertions, credentials),
    error: assertions.length ? null : 'An API script must contain an explicit assertion',
    completed_steps: steps.length,
  });
}
