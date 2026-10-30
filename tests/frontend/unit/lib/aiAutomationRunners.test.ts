import { describe, expect, it } from 'vitest';
import { runnerSupportsExecutionMode } from '@/lib/aiAutomationRunners';

describe('runnerSupportsExecutionMode', () => {
  it('lets a web runner execute AI and fixed scripts unless a mode list says otherwise', () => {
    const web = { runner_type: 'web', capabilities: { browser: 'chromium' } };
    expect(runnerSupportsExecutionMode(web, 'ai')).toBe(true);
    expect(runnerSupportsExecutionMode(web, 'script')).toBe(true);
    expect(runnerSupportsExecutionMode({ runner_type: 'web', capabilities: { execution_modes: ['script'] } }, 'ai')).toBe(false);
  });

  it('keeps mobile and API runners script-only until they advertise AI', () => {
    expect(runnerSupportsExecutionMode({ runner_type: 'mobile', capabilities: {} }, 'ai')).toBe(false);
    expect(runnerSupportsExecutionMode({ runner_type: 'api', capabilities: {} }, 'script')).toBe(true);
    expect(runnerSupportsExecutionMode({ runner_type: 'api', capabilities: { execution_modes: ['ai', 'script'] } }, 'ai')).toBe(true);
  });
});