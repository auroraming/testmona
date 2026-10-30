import { RunnerProtocol, delay } from '../../common/protocol.js';
import { executeApiScript } from './executor.js';

const protocol = new RunnerProtocol(process.env.TESTMONA_BACKEND_URL, process.env.TESTMONA_RUNNER_TOKEN);
const pollMs = Number(process.env.TESTMONA_RUNNER_POLL_MS || 3000);

async function run(lease) {
  if (lease.task.execution_mode !== 'script') return protocol.report(lease, 'blocked', null, 'API AI mode is not enabled yet');
  const baseUrl = lease.context?.environment?.config?.api_url || lease.context?.environment?.config?.base_url || lease.task.config?.base_url;
  if (!baseUrl) return protocol.report(lease, 'blocked', null, 'API base URL is required');
  let cancelled = false;
  const heartbeat = setInterval(() => protocol.heartbeat(lease).then((state) => { cancelled = state.cancel_requested; }).catch(console.error), 30000);
  try {
    const result = await executeApiScript({
      baseUrl, script: lease.task.config?.script, variables: lease.task.config?.variables || {}, shouldCancel: () => cancelled,
      emitEvidence: (item) => protocol.appendEvidence(lease, [item]),
    });
    return protocol.report(lease, result.cancelled ? 'cancelled' : result.passed ? 'passed' : 'failed', result, result.error);
  } finally { clearInterval(heartbeat); }
}

while (true) {
  try { const lease = await protocol.claim(); if (lease) await run(lease); else await delay(pollMs); }
  catch (error) { console.error(error); await delay(pollMs); }
}
