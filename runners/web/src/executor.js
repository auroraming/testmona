const SUPPORTED_ACTIONS = new Set([
  'navigate', 'click', 'fill', 'assert_text', 'assert_visible', 'screenshot',
]);
const NETWORK_SEQUENCE_BASE = 700_000;
const SECRET_QUERY_KEYS = /^(token|key|secret|password|authorization|code|session|access_token|api_key|apikey|sig|signature)$/i;

export function redactUrl(raw) {
  try {
    const url = new URL(String(raw));
    url.username = '';
    url.password = '';
    url.hash = '';
    for (const key of [...url.searchParams.keys()]) {
      if (SECRET_QUERY_KEYS.test(key)) url.searchParams.set(key, '[redacted]');
    }
    const text = url.toString();
    return text.length > 2000 ? `${text.slice(0, 2000)}…` : text;
  } catch {
    return '[invalid-url]';
  }
}

function attachNetwork(page, records) {
  if (!page || typeof page.on !== 'function') return;
  page.on('request', (request) => {
    if (records.length >= 50) return;
    records.push({
      method: request.method(),
      url: redactUrl(request.url()),
      resource_type: typeof request.resourceType === 'function' ? request.resourceType() : null,
      status: null,
    });
  });
  page.on('response', (response) => {
    const request = response.request();
    const url = redactUrl(request.url());
    const match = [...records].reverse().find((item) => item.url === url && item.status == null);
    if (match) match.status = response.status();
  });
}

async function flushNetwork(records, emitEvidence) {
  for (let index = 0; index < records.length; index += 1) {
    const item = records[index];
    await emitEvidence({
      sequence: NETWORK_SEQUENCE_BASE + index + 1,
      evidence_type: 'network',
      title: `${item.method || 'GET'} ${item.status ?? ''}`.trim(),
      status: 'completed',
      payload: {
        method: item.method,
        url: item.url,
        status: item.status,
        resource_type: item.resource_type,
      },
    });
  }
  records.length = 0;
}

export function validateScript(script) {
  if (!Array.isArray(script) || script.length === 0) {
    throw new Error('config.script must contain at least one Web step');
  }
  return script.map((step, index) => {
    if (!step || typeof step !== 'object' || !SUPPORTED_ACTIONS.has(step.action)) {
      throw new Error(`Unsupported Web action at step ${index + 1}`);
    }
    return step;
  });
}

export async function executeScript(page, script, emitEvidence, shouldCancel = () => false) {
  const assertions = [];
  const network = [];
  attachNetwork(page, network);
  const steps = validateScript(script);
  for (let index = 0; index < steps.length; index += 1) {
    if (shouldCancel()) {
      await flushNetwork(network, emitEvidence);
      return { passed: false, cancelled: true, assertions, error: 'Task cancelled', completed_steps: index };
    }
    const step = steps[index];
    const sequence = index + 1;
    const startedAt = Date.now();
    let payload = { action: step.action };
    let status = 'completed';
    try {
      if (step.action === 'navigate') {
        await page.goto(step.url, { waitUntil: step.wait_until || 'domcontentloaded' });
        payload.url = page.url();
      } else if (step.action === 'click') {
        await page.locator(step.selector).click();
      } else if (step.action === 'fill') {
        await page.locator(step.selector).fill(String(step.value ?? ''));
      } else if (step.action === 'assert_text') {
        const actual = await page.locator(step.selector).textContent();
        const passed = String(actual ?? '').includes(String(step.expected));
        assertions.push({ sequence, passed, expected: step.expected, actual });
        payload = { ...payload, assertion: assertions.at(-1) };
        status = passed ? 'passed' : 'failed';
        if (!passed) throw new Error(`Expected ${step.selector} to contain text`);
      } else if (step.action === 'assert_visible') {
        const passed = await page.locator(step.selector).isVisible();
        assertions.push({ sequence, passed, expected: true, actual: passed });
        payload = { ...payload, assertion: assertions.at(-1) };
        status = passed ? 'passed' : 'failed';
        if (!passed) throw new Error(`Expected ${step.selector} to be visible`);
      } else if (step.action === 'screenshot') {
        const artifactRef = `artifacts/step-${sequence}.png`;
        await page.screenshot({ path: artifactRef, fullPage: Boolean(step.full_page) });
        payload.local_artifact_path = artifactRef;
      }
      payload.duration_ms = Date.now() - startedAt;
      await emitEvidence({ sequence, evidence_type: step.action.startsWith('assert_') ? 'assertion' : 'step', title: step.action, status, payload });
    } catch (error) {
      payload.duration_ms = Date.now() - startedAt;
      payload.error = error instanceof Error ? error.message : 'Web step failed';
      await emitEvidence({ sequence, evidence_type: step.action.startsWith('assert_') ? 'assertion' : 'step', title: step.action, status: 'failed', payload });
      await flushNetwork(network, emitEvidence);
      return { passed: false, assertions, error: payload.error, completed_steps: sequence };
    }
  }
  await flushNetwork(network, emitEvidence);
  return {
    passed: assertions.length > 0 && assertions.every((item) => item.passed),
    assertions,
    error: assertions.length === 0 ? 'A Web script must contain at least one explicit assertion' : null,
    completed_steps: steps.length,
  };
}
