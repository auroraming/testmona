import { describe, expect, it } from 'vitest';
import { getPriorityLabel, getStandardDescription, getTestTypeLabel } from '../../../../frontend/src/lib/testTypeLabels';

const labels: Record<string, string> = {
  testTypeManual: '手工测试',
  testTypeRegression: '回归测试',
  low: '低',
  testTypeManualDescription: '手工测试，由测试人员执行',
};

describe('getTestTypeLabel', () => {
  it('translates standard test types case-insensitively', () => {
    expect(getTestTypeLabel('Manual', (key) => labels[key] ?? key)).toBe('手工测试');
    expect(getTestTypeLabel('REGRESSION', (key) => labels[key] ?? key)).toBe('回归测试');
  });

  it('keeps custom test type names unchanged', () => {
    expect(getTestTypeLabel('Payment flow', (key) => key)).toBe('Payment flow');
  });

  it('translates only standard priority names and descriptions', () => {
    const translate = (key: string) => labels[key] ?? key;
    expect(getPriorityLabel('Low', translate)).toBe('低');
    expect(getPriorityLabel('Blocker', translate)).toBe('Blocker');
    expect(getStandardDescription('Manual testing - executed by human testers', translate)).toBe('手工测试，由测试人员执行');
    expect(getStandardDescription('Run this flow by hand', translate)).toBe('Run this flow by hand');
  });
});
