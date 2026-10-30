import { chromium } from 'playwright';
import { readFile, unlink } from 'node:fs/promises';
import { executeWebAi } from './aiExecutor.js';
import { executeScript } from './executor.js';
import { RunnerProtocol, delay } from '../../common/protocol.js';

const backendUrl = process.env.TESTMONA_BACKEND_URL;
const runnerToken = process.env.TESTMONA_RUNNER_TOKEN;
const pollMs = Number(process.env.TESTMONA_RUNNER_POLL_MS || 3000);
if (!backendUrl || !runnerToken) throw new Error('TESTMONA_BACKEND_URL and TESTMONA_RUNNER_TOKEN are required');
const protocol = new RunnerProtocol(backendUrl, runnerToken);

async function runLease(lease) {
  const task = lease.task;
  if (task.execution_mode !== 'script') {
    await executeWebAi(lease, { protocol });
    return;
  }
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext();
  const page = await context.newPage();
  await context.tracing.start({ screenshots: true, snapshots: true, sources: true });
  let cancelRequested = false;
  const heartbeat = setInterval(() => {
    protocol.heartbeat(lease)
      .then((status) => { cancelRequested = Boolean(status.cancel_requested); })
      .catch(console.error);
  }, 30000);
  try {
    const result = await executeScript(page, task.config?.script, async (item) => {
      const localPath = item.payload.local_artifact_path;
      if (localPath) {
        const uploaded = await protocol.uploadArtifact(lease, await readFile(localPath), `step-${item.sequence}.png`, 'image/png');
        delete item.payload.local_artifact_path;
        item.artifact_ref = uploaded.artifact_ref;
        await unlink(localPath).catch(() => {});
      }
      await protocol.appendEvidence(lease, [item]);
    }, () => cancelRequested);
    const tracePath = `artifacts/task-${task.id}-trace.zip`;
    await context.tracing.stop({ path: tracePath });
    const trace = await protocol.uploadArtifact(lease, await readFile(tracePath), `task-${task.id}-trace.zip`, 'application/zip');
    await unlink(tracePath).catch(() => {});
    await protocol.appendEvidence(lease, [{
      sequence: (task.config?.script?.length || 0) + 1, evidence_type: 'trace', title: 'Playwright trace',
      status: 'completed', payload: {}, artifact_ref: trace.artifact_ref,
    }]);
    await protocol.report(lease, result.cancelled ? 'cancelled' : result.passed ? 'passed' : 'failed', result, result.error);
  } finally {
    clearInterval(heartbeat);
    await context.close();
    await browser.close();
  }
}

while (true) {
  try {
    const lease = await protocol.claim();
    if (lease) await runLease(lease);
    else await delay(pollMs);
  } catch (error) {
    console.error(error);
    await delay(pollMs);
  }
}
