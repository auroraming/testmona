import { describe, expect, it } from 'vitest';
import { getCurrentReviewRounds, getReviewCaseIds } from '@/components/TestCases/testCaseReviewUtils';
import type { TestCaseReviewTask } from '@/lib/api';

const round = (caseId: number, roundNumber: number, status: 'pending' | 'approved' | 'changes_requested') => ({
  id: caseId * 10 + roundNumber,
  test_case_id: caseId,
  test_case_title: `Case ${caseId}`,
  round_number: roundNumber,
  revision_number: roundNumber,
  snapshot: {},
  status,
  submitted_by: 1,
  created_at: '2026-10-31T00:00:00Z',
  assignments: [],
});

describe('test-case review helpers', () => {
  it('uses only the latest review round for each test case', () => {
    const task = { rounds: [round(1, 2, 'pending'), round(2, 1, 'approved'), round(1, 1, 'approved')] } as TestCaseReviewTask;
    expect(getCurrentReviewRounds(task).map((item) => [item.test_case_id, item.round_number])).toEqual([[1, 2], [2, 1]]);
  });

  it('expands a selected module to all descendant test cases', () => {
    const sections = [
      { id: '10', name: 'Parent', testCaseCount: 3, children: [
        { id: '11', name: 'Child', testCaseCount: 2, children: [
          { id: '12', name: 'Grandchild', testCaseCount: 1 },
        ] },
      ] },
      { id: '20', name: 'Other', testCaseCount: 1 },
    ];
    const cases = [
      { id: 1, section_id: 10 }, { id: 2, section_id: 11 }, { id: 3, section_id: 12 },
      { id: 4, section_id: 20 }, { id: 5 },
    ];
    expect(getReviewCaseIds({ kind: 'section', id: 10 }, undefined, sections, cases)).toEqual([1, 2, 3]);
    expect(getReviewCaseIds({ kind: 'case', id: 3 }, 3, sections, cases)).toEqual([3]);
    expect(getReviewCaseIds({ kind: 'suite', id: 1 }, undefined, sections, cases)).toEqual([1, 2, 3, 4, 5]);
  });
});
