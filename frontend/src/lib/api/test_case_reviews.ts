import { api } from './client';

export type TestCaseReviewDecision = 'pending' | 'approved' | 'changes_requested';
export type TestCaseReviewStatus = 'pending' | 'approved' | 'changes_requested';

export interface TestCaseReviewAssignment {
  id: number;
  reviewer_id: number;
  is_active: boolean;
  decision: TestCaseReviewDecision;
  comment?: string | null;
  has_suggestion: boolean;
  decided_at?: string | null;
  removed_at?: string | null;
}

export interface TestCaseReviewRound {
  id: number;
  test_case_id: number;
  test_case_title: string;
  round_number: number;
  revision_number: number;
  snapshot: Record<string, unknown>;
  status: TestCaseReviewStatus;
  submitted_by: number;
  created_at: string;
  resolved_at?: string | null;
  assignments: TestCaseReviewAssignment[];
}

export interface TestCaseReviewTask {
  id: number;
  project_id: number;
  test_suite_id: number;
  name: string;
  mode: 'single' | 'multiple';
  status: TestCaseReviewStatus;
  requested_by: number;
  due_at?: string | null;
  created_at: string;
  updated_at?: string | null;
  rounds: TestCaseReviewRound[];
}

export const testCaseReviewsAPI = {
  list: async (projectId: number): Promise<TestCaseReviewTask[]> =>
    (await api.get('/test-case-review-tasks', { params: { project_id: projectId } })).data,
  create: async (payload: {
    name: string;
    test_suite_id: number;
    test_case_ids: number[];
    reviewer_ids: number[];
    mode: 'single' | 'multiple';
    due_at?: string | null;
  }): Promise<TestCaseReviewTask> => (await api.post('/test-case-review-tasks', payload)).data,
  decide: async (
    roundId: number,
    payload: { decision: 'approved' | 'changes_requested'; comment?: string | null; has_suggestion?: boolean },
  ): Promise<TestCaseReviewTask> => (await api.post(`/test-case-review-rounds/${roundId}/decision`, payload)).data,
  updateReviewers: async (roundId: number, reviewerIds: number[]): Promise<TestCaseReviewTask> =>
    (await api.put(`/test-case-review-rounds/${roundId}/reviewers`, { reviewer_ids: reviewerIds })).data,
  rereview: async (taskId: number, testCaseIds?: number[]): Promise<TestCaseReviewTask> =>
    (await api.post(`/test-case-review-tasks/${taskId}/rereview`, { test_case_ids: testCaseIds ?? null })).data,
};
