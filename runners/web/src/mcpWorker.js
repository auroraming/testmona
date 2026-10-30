import { spawn } from 'node:child_process';
import { normalizeHttpOrigin } from './assertionProxy.js';

export const DEFAULT_PLAYWRIGHT_MCP_PACKAGE = '@playwright/mcp@0.0.83';
const PINNED_PACKAGE = /^@playwright\/mcp@\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$/u;

export function buildPlaywrightMcpArgs(packageRef, allowedOrigin) {
  if (!PINNED_PACKAGE.test(packageRef)) {
    throw new Error('package_ref must pin an exact @playwright/mcp semantic version');
  }
  const origin = normalizeHttpOrigin(allowedOrigin);
  return ['--yes', packageRef, '--headless', '--isolated', '--browser=chrome', '--block-service-workers', `--allowed-origins=${origin}`, '--idle-timeout=300000'];
}

export function encodeMessage(payload) {
  const body = JSON.stringify(payload);
  return `Content-Length: ${Buffer.byteLength(body)}\r\n\r\n${body}`;
}

export function createMessageParser(onMessage) {
  let buffer = Buffer.alloc(0);
  return (chunk) => {
    buffer = Buffer.concat([buffer, Buffer.from(chunk)]);
    while (buffer.length) {
      const headerEnd = buffer.indexOf('\r\n\r\n');
      if (headerEnd === -1) return;
      const match = /Content-Length:\s*(\d+)/iu.exec(buffer.subarray(0, headerEnd).toString('utf8'));
      if (!match) throw new Error('MCP response missing Content-Length');
      const length = Number(match[1]);
      const start = headerEnd + 4;
      if (buffer.length < start + length) return;
      onMessage(JSON.parse(buffer.subarray(start, start + length).toString('utf8')));
      buffer = buffer.subarray(start + length);
    }
  };
}

export function createStdioMcpClient(child, timeoutMs = 30000) {
  let nextId = 1;
  const pending = new Map();
  const parser = createMessageParser((message) => {
    const waiter = pending.get(message.id);
    if (!waiter) return;
    pending.delete(message.id);
    clearTimeout(waiter.timer);
    if (message.error) waiter.reject(new Error(message.error.message || 'MCP error'));
    else waiter.resolve(message.result);
  });
  child.stdout.on('data', parser);
  const request = (method, params) => new Promise((resolve, reject) => {
    const id = nextId;
    nextId += 1;
    const timer = setTimeout(() => {
      pending.delete(id);
      reject(new Error('MCP operation timed out'));
    }, timeoutMs);
    pending.set(id, { resolve, reject, timer });
    child.stdin.write(encodeMessage({ jsonrpc: '2.0', id, method, params }));
  });
  return {
    async health() {
      const result = await request('initialize', {
        protocolVersion: '2024-11-05',
        capabilities: {},
        clientInfo: { name: 'testmona-web-runner', version: '0.1.0' },
      });
      child.stdin.write(encodeMessage({ jsonrpc: '2.0', method: 'notifications/initialized' }));
      return Boolean(result);
    },
    async listTools() {
      const result = await request('tools/list', {});
      return result.tools || [];
    },
    async callTool(name, args) {
      const result = await request('tools/call', { name, arguments: args || {} });
      if (result?.isError) throw new Error(`Tool '${name}' returned an error`);
      return { content: result?.content || [], structured_content: result?.structuredContent || null };
    },
  };
}

export async function startPlaywrightMcpWorker({
  packageRef,
  allowedOrigin,
  workspace,
  command = 'npx',
  spawnImpl = spawn,
  clientFactory = null,
} = {}) {
  const args = buildPlaywrightMcpArgs(packageRef, allowedOrigin);
  const child = spawnImpl(command, args, { cwd: workspace, stdio: ['pipe', 'pipe', 'pipe'], env: process.env });
  let stopped = false;
  const stop = async () => {
    if (stopped) return;
    stopped = true;
    if (!child.killed) child.kill('SIGTERM');
  };
  try {
    const client = clientFactory ? clientFactory(child) : createStdioMcpClient(child);
    await client.health();
    return { client, stop, args };
  } catch (error) {
    await stop();
    throw error;
  }
}
