const ACTIONS = new Set(['tap', 'type', 'swipe', 'assert_text', 'assert_visible', 'screenshot']);

export async function executeMobileScript(driver, script, emitEvidence, shouldCancel = () => false) {
  if (!Array.isArray(script) || script.length === 0) throw new Error('config.script must contain Mobile steps');
  const assertions = [];
  for (let index = 0; index < script.length; index += 1) {
    if (shouldCancel()) return { passed: false, cancelled: true, assertions, error: 'Task cancelled' };
    const step = script[index]; const sequence = index + 1;
    if (!step || !ACTIONS.has(step.action)) throw new Error(`Unsupported Mobile action at step ${sequence}`);
    const payload = { action: step.action }; const startedAt = Date.now();
    try {
      if (step.action === 'swipe') await driver.swipe(step);
      else if (step.action === 'screenshot') { await driver.screenshot(); payload.screenshot_captured = true; }
      else {
        const element = await driver.find(step.selector);
        if (step.action === 'tap') await driver.click(element);
        if (step.action === 'type') await driver.type(element, step.value);
        if (step.action === 'assert_visible') {
          const assertion = { passed: Boolean(element), expected: true, actual: Boolean(element) };
          assertions.push(assertion); payload.assertion = assertion;
        }
        if (step.action === 'assert_text') {
          const actual = await driver.text(element); const passed = String(actual).includes(String(step.expected));
          const assertion = { passed, expected: step.expected, actual }; assertions.push(assertion); payload.assertion = assertion;
          if (!passed) throw new Error('assert_text failed');
        }
      }
      payload.duration_ms = Date.now() - startedAt;
      await emitEvidence({ sequence, evidence_type: step.action.startsWith('assert_') ? 'assertion' : step.action === 'screenshot' ? 'screenshot' : 'step', title: step.action, status: payload.assertion?.passed === false ? 'failed' : step.action.startsWith('assert_') ? 'passed' : 'completed', payload });
    } catch (error) {
      payload.duration_ms = Date.now() - startedAt; payload.error = error instanceof Error ? error.message : 'Mobile step failed';
      await emitEvidence({ sequence, evidence_type: step.action.startsWith('assert_') ? 'assertion' : 'step', title: step.action, status: 'failed', payload });
      return { passed: false, assertions, error: payload.error, completed_steps: sequence };
    }
  }
  return { passed: assertions.length > 0 && assertions.every((item) => item.passed), assertions, error: assertions.length ? null : 'A Mobile script must contain an explicit assertion', completed_steps: script.length };
}
