import { api } from './client';

export type AIAutomationRunnerType = 'web' | 'mobile' | 'api';
export type AIAutomationExecutionMode = 'ai' | 'script';

export interface AIAutomationTask {
  id: number;
  project_id: number;
  test_case_id?: number | null;
  test_run_id?: number | null;
  environment_id?: number | null;
  runner_type: AIAutomationRunnerType;
  execution_mode: AIAutomationExecutionMode;
  status: string;
  goal: string;
  max_steps: number;
  timeout_seconds: number;
  token_budget?: number | null;
  input_tokens: number;
  output_tokens: number;
  result?: Record<string, unknown> | null;
  error_message?: string | null;
  created_at: string;
  started_at?: string | null;
  completed_at?: string | null;
}

export interface AIAutomationEvidence {
  id: number;
  task_id: number;
  sequence: number;
  evidence_type: string;
  title: string;
  status?: string | null;
  payload: Record<string, unknown>;
  artifact_ref?: string | null;
  created_at: string;
}

export interface AIAutomationTaskCreate {
  project_id: number;
  runner_type: AIAutomationRunnerType;
  execution_mode: AIAutomationExecutionMode;
  goal: string;
  test_case_id?: number;
  environment_id?: number;
  max_steps: number;
  timeout_seconds: number;
  token_budget?: number;
  config: Record<string, unknown>;
}

export interface AIAutomationRunner {
  id: number;
  project_id: number;
  name: string;
  runner_type: AIAutomationRunnerType;
  capabilities: Record<string, unknown>;
  status: string;
  last_seen_at?: string | null;
}

export const aiAutomationAPI = {
  listTasks: async (projectId: number) => (await api.get<AIAutomationTask[]>('/ai-automation/tasks', { params: { project_id: projectId } })).data,
  listRunners: async (projectId: number) => (await api.get<AIAutomationRunner[]>('/ai-automation/runners', { params: { project_id: projectId } })).data,
  createTask: async (payload: AIAutomationTaskCreate) => (await api.post<AIAutomationTask>('/ai-automation/tasks', payload)).data,
  cancelTask: async (taskId: number) => (await api.post<AIAutomationTask>(`/ai-automation/tasks/${taskId}/cancel`)).data,
  listEvidence: async (taskId: number) => (await api.get<AIAutomationEvidence[]>(`/ai-automation/tasks/${taskId}/evidence`)).data,
};
