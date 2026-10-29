import { chromium } from 'playwright';
import { executeScript } from './executor.js';

const backendUrl = process.env.TESTMONA_BACKEND_URL;
const runnerToken = process.env.TESTMONA_RUNNER_TOKEN;
const pollMs = Number(process.env.TESTMONA_RUNNER_POLL_MS || 3000);
if (!backendUrl || !runnerToken) throw new Error('TESTMONA_BACKEND_URL and TESTMONA_RUNNER_TOKEN are required');

async function request(path, options = {}) {
  const response = await fetch(`${backendUrl.replace(/\/$/, '')}${path}`, {
    ...options,
    headers: { 'Content-Type': 'application/json', 'X-Runner-Token': runnerToken, ...(options.headers || {}) },
  });
  if (response.status === 204) return null;
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || `Runner protocol HTTP ${response.status}`);
  return data;
}

async function runLease(lease) {
  const task = lease.task;
  if (task.execution_mode !== 'script') {
    await request(`/internal/ai-automation/tasks/${task.id}/report`, {
      method: 'POST', body: JSON.stringify({ lease_token: lease.lease_token, status: 'blocked', error_message: 'Web AI mode requires the Playwright MCP integration' }),
    });
    return;
  }
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext();
  const page = await context.newPage();
  let cancelRequested = false;
  const heartbeat = setInterval(() => {
    request('/internal/ai-automation/heartbeat', { method: 'POST', body: JSON.stringify({ task_id: task.id, lease_token: lease.lease_token }) })
      .then((status) => { cancelRequested = Boolean(status.cancel_requested); })
      .catch(console.error);
  }, 30000);
  try {
    const result = await executeScript(page, task.config?.script, async (item) => {
      await request(`/internal/ai-automation/tasks/${task.id}/evidence`, {
        method: 'POST', body: JSON.stringify({ lease_token: lease.lease_token, items: [item] }),
      });
    }, () => cancelRequested);
    await request(`/internal/ai-automation/tasks/${task.id}/report`, {
      method: 'POST',
      body: JSON.stringify({ lease_token: lease.lease_token, status: result.cancelled ? 'cancelled' : result.passed ? 'passed' : 'failed', result, error_message: result.error }),
    });
  } finally {
    clearInterval(heartbeat);
    await context.close();
    await browser.close();
  }
}

while (true) {
  try {
    const lease = await request('/internal/ai-automation/claim', { method: 'POST' });
    if (lease) await runLease(lease);
    else await new Promise((resolve) => setTimeout(resolve, pollMs));
  } catch (error) {
    console.error(error);
    await new Promise((resolve) => setTimeout(resolve, pollMs));
  }
}
