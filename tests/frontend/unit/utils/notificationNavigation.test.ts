import { beforeEach, describe, expect, it, vi } from 'vitest';

const { get } = vi.hoisted(() => ({ get: vi.fn() }));
vi.mock('@/lib/api', () => ({ api: { get } }));

import { resolveNotificationTarget } from '@/lib/notificationNavigation';

describe('notification navigation', () => {
  beforeEach(() => get.mockReset());

  it('opens a test case review task in its project test case workspace', async () => {
    get.mockResolvedValue({ data: { id: 9, project_id: 4, test_suite_id: 7 } });
    await expect(resolveNotificationTarget({
      related_entity_type: 'test_case_review_task', related_entity_id: 9,
    })).resolves.toBe('/projects/4/test-cases');
    expect(get).toHaveBeenCalledWith('/test-case-review-tasks/9');
  });
});
