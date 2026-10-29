const SUPPORTED_ACTIONS = new Set([
  'navigate', 'click', 'fill', 'assert_text', 'assert_visible', 'screenshot',
]);

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
  const steps = validateScript(script);
  for (let index = 0; index < steps.length; index += 1) {
    if (shouldCancel()) return { passed: false, cancelled: true, assertions, error: 'Task cancelled', completed_steps: index };
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
      return { passed: false, assertions, error: payload.error, completed_steps: sequence };
    }
  }
  return {
    passed: assertions.length > 0 && assertions.every((item) => item.passed),
    assertions,
    error: assertions.length === 0 ? 'A Web script must contain at least one explicit assertion' : null,
    completed_steps: steps.length,
  };
}
