export const API_RESULT_SCHEMA = 'testmona.api_result.v1';

export function normalizeApiResult(source, reported = {}) {
  const assertions = (reported.assertions || []).filter((item) => item && typeof item === 'object').map((item) => ({
    name: String(item.name || item.action || 'assertion'),
    passed: Boolean(item.passed),
    expected: item.expected,
    actual: item.actual,
  }));
  const cancelled = Boolean(reported.cancelled);
  const passed = !cancelled && assertions.length > 0 && assertions.every((item) => item.passed);
  let error = null;
  if (cancelled) error = 'Task cancelled';
  else if (!passed) error = reported.error || (assertions.length ? 'assertion_failed' : 'missing_assertion');
  return {
    schema: API_RESULT_SCHEMA,
    source,
    passed,
    cancelled,
    assertions,
    error,
    completed_steps: reported.completed_steps ?? null,
  };
}
