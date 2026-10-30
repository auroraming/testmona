import { spawn } from 'node:child_process';
import { mkdtemp, rm } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { normalizeHttpOrigin } from './assertionProxy.js';

export const DEFAULT_PLAYWRIGHT_MCP_PACKAGE = '@playwright/mcp@0.0.83';
export const REQUIRED_PLAYWRIGHT_CORE = '1.64.1';
const PINNED_PACKAGE = /^@playwright\/mcp@\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$/u;

export function assertPinnedMcpPackage(packageRef) {
  if (!PINNED_PACKAGE.test(packageRef)) {
    throw new Error('package_ref must pin an exact @playwright/mcp semantic version');
  }
}

export function buildPlaywrightMcpArgs(allowedOrigin, outputDir, executablePath) {
  const origin = normalizeHttpOrigin(allowedOrigin);
  const args = [
    '--headless',
    '--isolated',
    '--block-service-workers',
    `--allowed-origins=${origin}`,
    '--idle-timeout=300000',
    '--image-responses=omit',
    `--output-dir=${outputDir}`,
  ];
  if (executablePath) args.push(`--executable-path=${executablePath}`);
  if (args.some((arg) => arg === '--browser=chrome' || arg.startsWith('--browser='))) {
    throw new Error('Web Runner must use the image Chromium, not a browser channel');
  }
  return args;
}

/** @playwright/mcp@0.0.83 reads one JSON object per line, not LSP Content-Length frames. */
export function encodeMessage(payload) {
  return `${JSON.stringify(payload)}\n`;
}

export function createMessageParser(onMessage) {
  let buffer = Buffer.alloc(0);
  return (chunk) => {
    buffer = Buffer.concat([buffer, Buffer.from(chunk)]);
    let newline = buffer.indexOf(0x0a);
    while (newline !== -1) {
      const line = buffer.subarray(0, newline).toString('utf8').replace(/\r$/u, '').trim();
      buffer = buffer.subarray(newline + 1);
      if (line) onMessage(JSON.parse(line));
      newline = buffer.indexOf(0x0a);
    }
  };
}

export function resolveInstalledMcpCli(packageRef = process.env.TESTMONA_PLAYWRIGHT_MCP_PACKAGE || DEFAULT_PLAYWRIGHT_MCP_PACKAGE) {
  assertPinnedMcpPackage(packageRef);
  const require = createRequire(import.meta.url);
  const installed = require('@playwright/mcp/package.json');
  if (`@playwright/mcp@${installed.version}` !== packageRef) {
    throw new Error(`Installed MCP @playwright/mcp@${installed.version} does not match ${packageRef}`);
  }
  const core = require('playwright-core/package.json');
  if (core.version !== REQUIRED_PLAYWRIGHT_CORE) {
    throw new Error(`Playwright MCP must use playwright-core ${REQUIRED_PLAYWRIGHT_CORE}, found ${core.version}`);
  }
  return path.join(path.dirname(require.resolve('@playwright/mcp/package.json')), 'cli.js');
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
  packageRef = process.env.TESTMONA_PLAYWRIGHT_MCP_PACKAGE || DEFAULT_PLAYWRIGHT_MCP_PACKAGE,
  allowedOrigin,
  command = process.execPath,
  spawnImpl = spawn,
  clientFactory = null,
  executablePath = process.env.TESTMONA_PLAYWRIGHT_EXECUTABLE || '',
} = {}) {
  assertPinnedMcpPackage(packageRef);
  const outputDir = await mkdtemp(path.join(tmpdir(), 'testmona-mcp-'));
  const toolArgs = buildPlaywrightMcpArgs(allowedOrigin, outputDir, executablePath || undefined);
  const prefix = clientFactory ? [] : [resolveInstalledMcpCli(packageRef)];
  const child = spawnImpl(command, [...prefix, ...toolArgs], {
    cwd: outputDir,
    stdio: ['pipe', 'pipe', 'pipe'],
    env: process.env,
  });
  let stopped = false;
  const stop = async () => {
    if (stopped) return;
    stopped = true;
    if (child && !child.killed) child.kill('SIGTERM');
    await rm(outputDir, { recursive: true, force: true });
  };
  try {
    const client = clientFactory ? clientFactory(child) : createStdioMcpClient(child);
    await client.health();
    return { client, stop, args: toolArgs, outputDir };
  } catch (error) {
    await stop();
    throw error;
  }
}
