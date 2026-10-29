const STANDARD_TEST_TYPE_KEYS: Record<string, string> = {
  automated: 'testTypeAutomated',
  integration: 'testTypeIntegration',
  manual: 'testTypeManual',
  performance: 'testTypePerformance',
  regression: 'testTypeRegression',
  security: 'testTypeSecurity',
  smoke: 'testTypeSmoke',
  usability: 'testTypeUsability',
};

const STANDARD_DESCRIPTION_KEYS: Record<string, string> = {
  'manual testing - executed by human testers': 'testTypeManualDescription',
  'automated testing - executed by scripts/tools': 'testTypeAutomatedDescription',
  'smoke testing - basic functionality checks': 'testTypeSmokeDescription',
  'regression testing - verify existing functionality': 'testTypeRegressionDescription',
  'integration testing - test component interactions': 'testTypeIntegrationDescription',
  'security testing - identify vulnerabilities': 'testTypeSecurityDescription',
  'performance testing - measure system performance': 'testTypePerformanceDescription',
  'usability testing - evaluate user experience': 'testTypeUsabilityDescription',
  'critical priority - immediate attention required': 'priorityCriticalDescription',
  'high priority - urgent attention required': 'priorityHighDescription',
  'medium priority - normal attention required': 'priorityMediumDescription',
  'low priority - can be addressed later': 'priorityLowDescription',
};

export function getTestTypeLabel(
  name: string,
  translate: (key: string) => string,
): string {
  const key = STANDARD_TEST_TYPE_KEYS[name.trim().toLowerCase()];
  return key ? translate(key) : name;
}

export function getStandardDescription(
  description: string,
  translate: (key: string) => string,
): string {
  const key = STANDARD_DESCRIPTION_KEYS[description.trim().toLowerCase()];
  return key ? translate(key) : description;
}

export function getPriorityLabel(
  name: string,
  translate: (key: string) => string,
): string {
  const key = name.trim().toLowerCase();
  return ['critical', 'high', 'medium', 'low'].includes(key) ? translate(key) : name;
}
