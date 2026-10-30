import test from 'node:test';
import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import { spawn } from 'node:child_process';
import { buildPlaywrightMcpArgs, createMessageParser, createStdioMcpClient, encodeMessage, resolveInstalledMcpCli, startPlaywrightMcpWorker } from '../src/mcpWorker.js';
import { PlaywrightAssertionProxy } from '../src/assertionProxy.js';

test('builds the image Chromium command without a Chrome channel', () => {
  const args = buildPlaywrightMcpArgs('https://example.test:8443', '/tmp/testmona-mcp-output');
  assert.deepEqual(args, [
    '--headless', '--isolated', '--block-service-workers',
    '--allowed-origins=https://example.test:8443', '--idle-timeout=300000',
    '--image-responses=omit', '--output-dir=/tmp/testmona-mcp-output',
  ]);
  assert.equal(args.includes('--browser=chrome'), false);
  assert.equal(encodeMessage({ ok: true }).includes('Content-Length'), false);
  assert.throws(() => buildPlaywrightMcpArgs('https://example.test/app', '/tmp/out'), /origin/);
});

test('parses newline JSON split across chunks', () => {
  const messages = [];
  const parser = createMessageParser((message) => messages.push(message));
  const encoded = Buffer.from(encodeMessage({ jsonrpc: '2.0', id: 1, result: { ok: true } }));
  parser(encoded.subarray(0, 12));
  assert.equal(messages.length, 0);
  parser(encoded.subarray(12));
  assert.deepEqual(messages, [{ jsonrpc: '2.0', id: 1, result: { ok: true } }]);
});

test('stdio client initializes and stops the process when health fails', async () => {
  const child = fakeChild();
  const client = createStdioMcpClient(child);
  assert.equal(await client.health(), true);
  const failed = { killed: false, kill(signal) { this.killed = signal; } };
  await assert.rejects(() => startPlaywrightMcpWorker({
    packageRef: '@playwright/mcp@0.0.83',
    allowedOrigin: 'https://example.test',
    workspace: '/tmp',
    spawnImpl: () => failed,
    clientFactory: () => ({ health: async () => { throw new Error('down'); } }),
  }), /down/);
  assert.equal(failed.killed, 'SIGTERM');
});

test('installed Playwright MCP accepts newline JSON', async () => {
  let cli;
  try {
    cli = resolveInstalledMcpCli('@playwright/mcp@0.0.83');
  } catch {
    return;
  }
  const child = spawn(process.execPath, [
    cli, '--headless', '--isolated', '--block-service-workers',
    '--allowed-origins=https://example.test', '--idle-timeout=300000', '--image-responses=omit',
  ], { stdio: ['pipe', 'pipe', 'pipe'] });
  const client = createStdioMcpClient(child, 8000);
  try {
    assert.equal(await client.health(), true);
    const proxy = new PlaywrightAssertionProxy(client, 'https://example.test');
    const names = (await proxy.discoverTools()).map((tool) => tool.name);
    assert.ok(names.includes('browser_assert_text'));
    assert.equal(names.includes('browser_evaluate'), false);
    assert.equal(names.includes('browser_file_upload'), false);
  } finally {
    child.kill('SIGTERM');
  }
});

test('newline JSON handshake can enter the assertion loop', async () => {
  const child = spawn(process.execPath, ['--input-type=module', '-e', NEWLINE_MCP], { stdio: ['pipe', 'pipe', 'pipe'] });
  const client = createStdioMcpClient(child, 3000);
  try {
    assert.equal(await client.health(), true);
    const proxy = new PlaywrightAssertionProxy(client, 'https://example.test');
    const names = (await proxy.discoverTools()).map((tool) => tool.name);
    assert.ok(names.includes('browser_assert_text'));
    const passed = await proxy.callTool('browser_assert_text', { expected: 'Welcome' });
    const letter = await proxy.callTool('browser_assert_text', { expected: 'e' });
    assert.equal(passed.structured_content.passed, true);
    assert.equal(letter.structured_content.passed, false);
  } finally {
    child.kill('SIGTERM');
  }
});

const NEWLINE_MCP = `
let buffer = '';
process.stdin.setEncoding('utf8');
process.stdin.on('data', (chunk) => {
  buffer += chunk;
  let index;
  while ((index = buffer.indexOf('\\n')) !== -1) {
    const line = buffer.slice(0, index);
    buffer = buffer.slice(index + 1);
    if (!line.trim()) continue;
    const message = JSON.parse(line);
    if (!Object.hasOwn(message, 'id')) continue;
    let result = {};
    if (message.method === 'initialize') {
      result = { protocolVersion: '2024-11-05', capabilities: {}, serverInfo: { name: 'newline', version: '0' } };
    } else if (message.method === 'tools/list') {
      result = { tools: [{ name: 'browser_snapshot', description: 'snapshot', inputSchema: { type: 'object' } }] };
    } else if (message.method === 'tools/call') {
      result = { content: [{ type: 'text', text: 'heading "Welcome"' }] };
    }
    process.stdout.write(JSON.stringify({ jsonrpc: '2.0', id: message.id, result }) + '\\n');
  }
});
`;

function fakeChild() {
  const stdout = new EventEmitter();
  const stdin = {
    write(chunk) {
      const parser = createMessageParser((message) => {
        if (message.method === 'initialize') {
          stdout.emit('data', Buffer.from(encodeMessage({ jsonrpc: '2.0', id: message.id, result: { protocolVersion: '2024-11-05' } })));
        }
      });
      parser(Buffer.from(chunk));
    },
  };
  return { stdin, stdout, stderr: new EventEmitter(), killed: false, kill() { this.killed = true; } };
}
