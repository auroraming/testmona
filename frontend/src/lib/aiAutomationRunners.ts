import type { AIAutomationExecutionMode, AIAutomationRunnerType } from '@/lib/api/ai_automation';

interface RunnerModeSource {
  runner_type: AIAutomationRunnerType | string;
  capabilities?: { execution_modes?: unknown } | null;
}

/**
 * Web runners execute both fixed scripts and Playwright MCP exploration.
 * An explicit execution_modes list still wins. Mobile and API stay script-only
 * until they advertise AI mode.
 */
export function runnerSupportsExecutionMode(runner: RunnerModeSource, executionMode: AIAutomationExecutionMode | string): boolean {
  const modes = runner.capabilities?.execution_modes;
  if (Array.isArray(modes)) return modes.includes(executionMode);
  if (runner.runner_type === 'web') return executionMode === 'ai' || executionMode === 'script';
  return executionMode === 'script';
}
