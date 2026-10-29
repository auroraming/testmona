import { RunnerProtocol, delay } from '../../common/protocol.js';
import { AppiumClient } from './appium.js';
import { executeMobileScript } from './executor.js';

const protocol = new RunnerProtocol(process.env.TESTMONA_BACKEND_URL, process.env.TESTMONA_RUNNER_TOKEN);
const pollMs = Number(process.env.TESTMONA_RUNNER_POLL_MS || 3000);

async function run(lease) {
  const appiumUrl = lease.context?.environment?.config?.appium_url || process.env.APPIUM_URL;
  if (!appiumUrl) return protocol.report(lease, 'blocked', null, 'No Appium endpoint is configured');
  if (lease.task.execution_mode !== 'script') return protocol.report(lease, 'blocked', null, 'Mobile AI mode requires mobile-mcp integration');
  const driver = new AppiumClient(appiumUrl);
  let cancelled = false;
  try {
    await driver.status();
    await driver.createSession(lease.task.config?.capabilities || {});
  } catch (error) {
    return protocol.report(lease, 'blocked', null, `No usable mobile device: ${error.message}`);
  }
  const heartbeat = setInterval(() => protocol.heartbeat(lease).then((state) => { cancelled = state.cancel_requested; }).catch(console.error), 30000);
  try {
    const result = await executeMobileScript(driver, lease.task.config?.script, async (item) => {
      if (item.payload.screenshot_base64) {
        const bytes = Buffer.from(item.payload.screenshot_base64, 'base64');
        delete item.payload.screenshot_base64;
        const uploaded = await protocol.uploadArtifact(lease, bytes, `step-${item.sequence}.png`, 'image/png');
        item.artifact_ref = uploaded.artifact_ref;
      }
      await protocol.appendEvidence(lease, [item]);
    }, () => cancelled);
    return protocol.report(lease, result.cancelled ? 'cancelled' : result.passed ? 'passed' : 'failed', result, result.error);
  } finally { clearInterval(heartbeat); await driver.close().catch(console.error); }
}

while (true) {
  try { const lease = await protocol.claim(); if (lease) await run(lease); else await delay(pollMs); }
  catch (error) { console.error(error); await delay(pollMs); }
}
