import test from 'node:test';
import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import { buildPlaywrightMcpArgs, createMessageParser, createStdioMcpClient, encodeMessage, startPlaywrightMcpWorker } from '../src/mcpWorker.js';

test('builds the pinned isolated Playwright MCP command', () => {
  const args = buildPlaywrightMcpArgs('@playwright/mcp@0.0.83', 'https://example.test:8443');
  assert.deepEqual(args, [
    '--yes', '@playwright/mcp@0.0.83', '--headless', '--isolated', '--browser=chrome',
    '--block-service-workers', '--allowed-origins=https://example.test:8443', '--idle-timeout=300000',
  ]);
  assert.throws(() => buildPlaywrightMcpArgs('@playwright/mcp@latest', 'https://example.test'), /exact/);
  assert.throws(() => buildPlaywrightMcpArgs('@playwright/mcp@0.0.83', 'https://example.test/app'), /origin/);
});

test('parses a Content-Length frame split across chunks', () => {
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
